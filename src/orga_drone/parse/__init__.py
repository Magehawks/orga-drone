"""Parsers for DJI filenames, SRT telemetry, EXIF, and MP4 model hints."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

DJI_NAME_RE = re.compile(
    r"^DJI_(?P<ts>\d{14})_(?P<seq>\d{4})_(?P<mode>[A-Z])\.(?P<ext>[A-Za-z0-9]+)$",
    re.IGNORECASE,
)

SRT_GPS_RE = re.compile(
    r"\[latitude:\s*(?P<lat>-?\d+(?:\.\d+)?)\]\s*\[longitude:\s*(?P<lon>-?\d+(?:\.\d+)?)\]",
    re.IGNORECASE,
)
SRT_ALT_RE = re.compile(
    r"\[rel_alt:\s*(?P<rel>-?\d+(?:\.\d+)?)\s+abs_alt:\s*(?P<abs>-?\d+(?:\.\d+)?)\]",
    re.IGNORECASE,
)

# Camera model codes → friendly names (extend over time)
CAMERA_MODEL_MAP = {
    "FC8485": "DJI Avata 2",
}

VIDEO_EXTS = {".mp4", ".mov", ".mkv"}
PHOTO_EXTS = {".jpg", ".jpeg", ".dng", ".png"}
PROXY_EXTS = {".lrf"}
SUBTITLE_EXTS = {".srt"}


@dataclass
class FilenameMeta:
    recorded_at: datetime | None
    sequence: int | None
    mode: str | None
    stem_base: str  # without extension, for sibling matching


@dataclass
class GpsPoint:
    lat: float
    lon: float
    abs_alt: float | None = None
    rel_alt: float | None = None
    t: float | None = None  # seconds from clip start (SRT cue time), if known


@dataclass
class ParsedMedia:
    path: Path
    kind: str  # video | photo | proxy | subtitle | other
    size_bytes: int
    recorded_at: datetime | None
    sequence: int | None
    mode: str | None
    stem_base: str
    drone_model: str | None = None
    camera_model: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    abs_alt: float | None = None
    duration_s: float | None = None
    track: list[GpsPoint] | None = None


def classify_ext(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in PHOTO_EXTS:
        return "photo"
    if ext in PROXY_EXTS:
        return "proxy"
    if ext in SUBTITLE_EXTS:
        return "subtitle"
    return "other"


def parse_filename(path: Path) -> FilenameMeta:
    match = DJI_NAME_RE.match(path.name)
    if not match:
        return FilenameMeta(None, None, None, path.stem)
    ts = datetime.strptime(match.group("ts"), "%Y%m%d%H%M%S")
    return FilenameMeta(
        recorded_at=ts,
        sequence=int(match.group("seq")),
        mode=match.group("mode").upper(),
        stem_base=path.stem,
    )


def _dms_to_decimal(values: tuple, ref: str) -> float:
    deg, minutes, seconds = (float(v) for v in values)
    decimal = deg + minutes / 60.0 + seconds / 3600.0
    if ref in {"S", "W"}:
        decimal = -decimal
    return decimal


def parse_exif_gps(path: Path) -> tuple[GpsPoint | None, str | None, str | None]:
    """Return (gps, make/model friendly, camera model code)."""
    try:
        with Image.open(path) as img:
            raw = img._getexif() or {}
    except Exception:
        return None, None, None

    tags = {TAGS.get(k, k): v for k, v in raw.items()}
    make = str(tags.get("Make") or "").strip()
    model = str(tags.get("Model") or "").strip()
    camera = model or None
    drone = CAMERA_MODEL_MAP.get(model) if model else None
    if not drone and make.upper() == "DJI" and model:
        drone = f"DJI {model}"

    gps_info = tags.get("GPSInfo")
    if not gps_info:
        return None, drone, camera

    gps = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}
    try:
        lat = _dms_to_decimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
        lon = _dms_to_decimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
        alt = float(gps["GPSAltitude"]) if "GPSAltitude" in gps else None
        return GpsPoint(lat, lon, abs_alt=alt), drone, camera
    except Exception:
        return None, drone, camera


def _srt_timecode_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(path: Path, *, max_track_points: int = 200) -> tuple[GpsPoint | None, list[GpsPoint], float | None]:
    """Parse DJI SRT: start GPS, sampled track, approximate duration from last cue."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None, [], None

    points: list[GpsPoint] = []
    duration_s: float | None = None

    # Cue start times for associating GPS samples with video time
    cue_times: list[tuple[int, float]] = []
    for tm in re.finditer(
        r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})",
        text,
    ):
        t0 = _srt_timecode_to_seconds(tm.group(1), tm.group(2), tm.group(3), tm.group(4))
        t1 = _srt_timecode_to_seconds(tm.group(5), tm.group(6), tm.group(7), tm.group(8))
        cue_times.append((tm.start(), t0))
        duration_s = t1

    def _cue_time_at(pos: int) -> float | None:
        if not cue_times:
            return None
        best: float | None = None
        for start, t0 in cue_times:
            if start <= pos:
                best = t0
            else:
                break
        return best

    for match in SRT_GPS_RE.finditer(text):
        lat = float(match.group("lat"))
        lon = float(match.group("lon"))
        if abs(lat) < 0.0001 and abs(lon) < 0.0001:
            continue
        abs_alt = rel_alt = None
        # Look nearby for altitude in the same cue block
        window = text[match.start() : match.start() + 200]
        alt_m = SRT_ALT_RE.search(window)
        if alt_m:
            rel_alt = float(alt_m.group("rel"))
            abs_alt = float(alt_m.group("abs"))
        points.append(
            GpsPoint(
                lat,
                lon,
                abs_alt=abs_alt,
                rel_alt=rel_alt,
                t=_cue_time_at(match.start()),
            )
        )

    if not points:
        return None, [], duration_s

    # Sample track evenly (keeps per-point timestamps when present)
    if len(points) <= max_track_points:
        track = points
    else:
        step = max(1, len(points) // max_track_points)
        track = points[::step][:max_track_points]
        if track[-1] is not points[-1]:
            track.append(points[-1])

    return points[0], track, duration_s


def detect_drone_from_mp4(path: Path, *, read_bytes: int = 2_000_000) -> tuple[str | None, str | None]:
    """Best-effort scan of MP4 header/meta for DJI model strings."""
    try:
        with path.open("rb") as fh:
            data = fh.read(read_bytes)
    except OSError:
        return None, None

    text = data.decode("latin-1", errors="ignore")
    camera = None
    drone = None

    m_cam = re.search(r"DJI\s+(FC\d+)", text, re.IGNORECASE)
    if m_cam:
        camera = m_cam.group(1).upper()
        drone = CAMERA_MODEL_MAP.get(camera, f"DJI {camera}")

    m_name = re.search(r"DJI\s*Avata\s*2", text, re.IGNORECASE)
    if m_name:
        drone = "DJI Avata 2"
        camera = camera or "FC8485"

    if re.search(r"AVATA2\.proto", text, re.IGNORECASE):
        drone = drone or "DJI Avata 2"
        camera = camera or "FC8485"

    return drone, camera


def parse_media_file(path: Path) -> ParsedMedia:
    path = path.resolve()
    fn = parse_filename(path)
    kind = classify_ext(path)
    size = path.stat().st_size if path.exists() else 0

    media = ParsedMedia(
        path=path,
        kind=kind,
        size_bytes=size,
        recorded_at=fn.recorded_at,
        sequence=fn.sequence,
        mode=fn.mode,
        stem_base=fn.stem_base,
    )

    if kind == "photo":
        gps, drone, camera = parse_exif_gps(path)
        media.drone_model = drone
        media.camera_model = camera
        if gps:
            media.latitude = gps.lat
            media.longitude = gps.lon
            media.abs_alt = gps.abs_alt

    elif kind == "subtitle":
        start, track, duration = parse_srt(path)
        media.duration_s = duration
        media.track = track
        if start:
            media.latitude = start.lat
            media.longitude = start.lon
            media.abs_alt = start.abs_alt

    elif kind == "video":
        drone, camera = detect_drone_from_mp4(path)
        media.drone_model = drone
        media.camera_model = camera
        # Prefer sibling SRT for GPS/duration
        srt = path.with_suffix(".SRT")
        if not srt.exists():
            srt = path.with_suffix(".srt")
        if srt.exists():
            start, track, duration = parse_srt(srt)
            media.duration_s = duration
            media.track = track
            if start:
                media.latitude = start.lat
                media.longitude = start.lon
                media.abs_alt = start.abs_alt

    return media
