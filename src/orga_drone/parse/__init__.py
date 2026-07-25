"""Parsers for DJI filenames, SRT telemetry, EXIF, and generic photo/video metadata."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.ExifTags import Base, GPSTAGS, TAGS

_HEIF_REGISTERED: bool | None = None


def ensure_heif_support() -> bool:
    """Register pillow-heif once so HEIC/HEIF open via Pillow (optional at runtime)."""
    global _HEIF_REGISTERED
    if _HEIF_REGISTERED is not None:
        return _HEIF_REGISTERED
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
        _HEIF_REGISTERED = True
    except Exception:
        _HEIF_REGISTERED = False
    return _HEIF_REGISTERED


# Register early when the dependency is installed (no-op if missing).
ensure_heif_support()

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

# QuickTime / ISO 6709 location (often in MOV/MP4 metadata atoms)
ISO6709_RE = re.compile(
    r"(?<![0-9A-Za-z])([+-]\d{1,2}(?:\.\d+)?)([+-]\d{1,3}(?:\.\d+)?)(?:([+-]\d+(?:\.\d+)?))?/"
)

CREATION_TIME_RE = re.compile(
    r"creation[_-]?(?:date|time)[^\d]{0,32}"
    r"(\d{4}[-:]\d{2}[-:]\d{2}[T ]\d{2}:\d{2}:\d{2})",
    re.IGNORECASE,
)

# Camera model codes → friendly names (extend over time)
CAMERA_MODEL_MAP = {
    "FC8485": "DJI Avata 2",
}

# Brand-agnostic common containers (phones, cameras, action cams, …).
# HEIC/HEIF need pillow-heif (declared dependency); opener registers at import.
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v"}
PHOTO_EXTS = {".jpg", ".jpeg", ".dng", ".png", ".webp", ".heic", ".heif"}
PROXY_EXTS = {".lrf"}
SUBTITLE_EXTS = {".srt"}

NON_DJI_CAMERA_LABEL = "Camera"

# Heuristic EXIF Make sets for source_type (brand-agnostic; not a whitelist for indexing).
_PHONE_MAKES = {
    "APPLE",
    "SAMSUNG",
    "GOOGLE",
    "XIAOMI",
    "HUAWEI",
    "ONEPLUS",
    "OPPO",
    "VIVO",
    "REALME",
    "MOTOROLA",
    "HTC",
    "LG ELECTRONICS",
    "LG",
    "NOKIA",
    "NOTHING",
    "ASUS",
    "FAIRPHONE",
    "HONOR",
    "TECNO",
    "INFINIX",
    "MEIZU",
    "SONY MOBILE",
}
_CAMERA_MAKES = {
    "CANON",
    "NIKON",
    "NIKON CORPORATION",
    "SONY",
    "FUJIFILM",
    "OLYMPUS",
    "OLYMPUS CORPORATION",
    "PANASONIC",
    "LEICA",
    "LEICA CAMERA AG",
    "GOPRO",
    "RICOH",
    "PENTAX",
    "SIGMA",
    "HASSELBLAD",
    "KODAK",
    "PHASE ONE",
    "BLACKMAGIC",
    "INSTA360",
}


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
    source_type: str | None = None  # drone | camera | phone | unknown
    exif_make: str | None = None


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


def _parse_exif_datetime(raw: object) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # EXIF: "YYYY:MM:DD HH:MM:SS" (also accept ISO-ish variants)
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _file_mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def _drone_label_from_make_model(make: str, model: str) -> tuple[str | None, str | None]:
    """Return (drone_model, camera_model) from EXIF/Make-Model style fields."""
    camera = model or None
    drone = CAMERA_MODEL_MAP.get(model) if model else None
    make_u = make.upper()
    if not drone and make_u == "DJI" and model:
        drone = f"DJI {model}"
    if not drone and (make or model):
        # Non-DJI phone/camera photos: show under a generic label in filters/UI.
        if make_u != "DJI":
            drone = NON_DJI_CAMERA_LABEL
    return drone, camera


def parse_exif_gps(path: Path) -> tuple[GpsPoint | None, str | None, str | None]:
    """Return (gps, drone label, camera model code). Backward-compatible wrapper."""
    gps, drone, camera, _recorded, _make = parse_exif(path)
    return gps, drone, camera


def classify_source_type(
    *,
    filename: str,
    mode: str | None = None,
    drone_model: str | None = None,
    camera_model: str | None = None,
    make: str | None = None,
) -> str:
    """Classify media origin: drone | camera | phone | unknown (for filters)."""
    if DJI_NAME_RE.match(Path(filename).name) or mode:
        return "drone"

    blob = " ".join(x for x in (drone_model, camera_model, make) if x).upper()
    if "DJI" in blob or "AVATA" in blob or re.search(r"\bFC\d{3,}", blob):
        return "drone"

    make_u = (make or "").strip().upper()
    model_u = (camera_model or "").strip().upper()
    if any(tok in model_u for tok in ("IPHONE", "PIXEL", "XPERIA", "GALAXY")):
        return "phone"
    if make_u in _PHONE_MAKES or make_u.startswith("SAMSUNG"):
        return "phone"
    if make_u in _CAMERA_MAKES or "GOPRO" in make_u or "INSTA360" in make_u:
        return "camera"
    if drone_model == NON_DJI_CAMERA_LABEL or make_u or model_u:
        # Known non-DJI EXIF device without a phone/camera make match → camera bucket
        return "camera"
    return "unknown"


def _exif_tags_from_image(img: Image.Image) -> dict:
    """Brand-agnostic EXIF dict (JPEG/PNG/WebP/HEIC). Prefer getexif (HEIC-safe)."""
    tags: dict = {}
    try:
        exif = img.getexif()
    except Exception:
        exif = None
    if exif:
        tags.update({TAGS.get(k, k): v for k, v in exif.items()})
        # GPS IFD is often only available via get_ifd (esp. HEIC / modern Pillow).
        try:
            gps_ifd = exif.get_ifd(Base.GPSInfo)
        except Exception:
            gps_ifd = None
        if gps_ifd:
            tags["GPSInfo"] = gps_ifd
        return tags

    # Legacy fallback for rare codecs that only expose _getexif
    try:
        raw = img._getexif() or {}  # type: ignore[attr-defined]
    except Exception:
        raw = {}
    if raw:
        tags.update({TAGS.get(k, k): v for k, v in raw.items()})
    return tags


def parse_exif(
    path: Path,
) -> tuple[GpsPoint | None, str | None, str | None, datetime | None, str | None]:
    """Return (gps, drone label, camera model, DateTimeOriginal/DateTime, make).

    Works for any camera brand when EXIF is present (phones, DSLRs, action cams).
    DJI make/model mapping remains an enhancement on top.
    """
    ensure_heif_support()
    try:
        with Image.open(path) as img:
            tags = _exif_tags_from_image(img)
    except Exception:
        return None, None, None, None, None

    make = str(tags.get("Make") or "").strip()
    model = str(tags.get("Model") or "").strip()
    drone, camera = _drone_label_from_make_model(make, model)
    recorded = _parse_exif_datetime(tags.get("DateTimeOriginal")) or _parse_exif_datetime(
        tags.get("DateTime")
    )

    gps_info = tags.get("GPSInfo")
    if not gps_info:
        return None, drone, camera, recorded, make or None

    gps = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}
    try:
        lat = _dms_to_decimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
        lon = _dms_to_decimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
        alt = float(gps["GPSAltitude"]) if "GPSAltitude" in gps else None
        return GpsPoint(lat, lon, abs_alt=alt), drone, camera, recorded, make or None
    except Exception:
        return None, drone, camera, recorded, make or None


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


def _parse_iso6709(text: str) -> GpsPoint | None:
    match = ISO6709_RE.search(text)
    if not match:
        return None
    try:
        lat = float(match.group(1))
        lon = float(match.group(2))
        alt = float(match.group(3)) if match.group(3) else None
    except ValueError:
        return None
    if abs(lat) < 0.0001 and abs(lon) < 0.0001:
        return None
    if abs(lat) > 90 or abs(lon) > 180:
        return None
    return GpsPoint(lat, lon, abs_alt=alt)


def _parse_creation_time(text: str) -> datetime | None:
    match = CREATION_TIME_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace("T", " ", 1).replace("Z", "").strip()
    # Normalize EXIF-style separators: 2024:06:15 12:30:00
    if len(raw) >= 10 and raw[4] == ":" and raw[7] == ":":
        raw = f"{raw[0:4]}-{raw[5:7]}-{raw[8:]}"
    return _parse_exif_datetime(raw[:19])


def _normalize_tag_datetime(value: str) -> datetime | None:
    cleaned = value.replace("Z", "").strip().replace("T", " ", 1)
    if len(cleaned) >= 10 and cleaned[4] == ":" and cleaned[7] == ":":
        cleaned = f"{cleaned[0:4]}-{cleaned[5:7]}-{cleaned[8:]}"
    return _parse_exif_datetime(cleaned[:19]) or _parse_creation_time(f"creation_time {value}")


def probe_video_with_ffprobe(
    path: Path,
) -> tuple[GpsPoint | None, datetime | None, float | None]:
    """Best-effort GPS / creation time / duration via system ffprobe (if installed)."""
    from orga_drone.ffmpeg_bin import find_ffprobe

    ffprobe = find_ffprobe()
    if not ffprobe:
        return None, None, None
    cmd = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None, None
    if proc.returncode != 0 or not proc.stdout:
        return None, None, None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, None, None

    tags: dict[str, str] = {}
    fmt = data.get("format") or {}
    if isinstance(fmt.get("tags"), dict):
        tags.update({str(k).lower(): str(v) for k, v in fmt["tags"].items()})
    for stream in data.get("streams") or []:
        if isinstance(stream.get("tags"), dict):
            tags.update({str(k).lower(): str(v) for k, v in stream["tags"].items()})

    gps = None
    for key in (
        "location",
        "location-eng",
        "com.apple.quicktime.location.iso6709",
    ):
        if key in tags:
            gps = _parse_iso6709(tags[key])
            if gps:
                break
    if gps is None:
        for value in tags.values():
            gps = _parse_iso6709(value)
            if gps:
                break

    recorded = None
    for key in ("creation_time", "com.apple.quicktime.creationdate", "date"):
        if key in tags:
            recorded = _normalize_tag_datetime(tags[key])
            if recorded:
                break

    duration_s = None
    try:
        if fmt.get("duration") is not None:
            duration_s = float(fmt["duration"])
    except (TypeError, ValueError):
        duration_s = None

    return gps, recorded, duration_s


def detect_drone_from_mp4(path: Path, *, read_bytes: int = 2_000_000) -> tuple[str | None, str | None]:
    """Best-effort scan of MP4 header/meta for DJI model strings."""
    drone, camera, _gps, _created = scan_video_header(path, read_bytes=read_bytes)
    return drone, camera


def scan_video_header(
    path: Path, *, read_bytes: int = 2_000_000
) -> tuple[str | None, str | None, GpsPoint | None, datetime | None]:
    """Scan container header for DJI model, ISO6709 GPS, and creation_time hints."""
    try:
        with path.open("rb") as fh:
            data = fh.read(read_bytes)
    except OSError:
        return None, None, None, None

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

    gps = _parse_iso6709(text)
    created = _parse_creation_time(text)
    return drone, camera, gps, created


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
        gps, drone, camera, exif_dt, make = parse_exif(path)
        media.drone_model = drone
        media.camera_model = camera
        media.exif_make = make
        if gps:
            media.latitude = gps.lat
            media.longitude = gps.lon
            media.abs_alt = gps.abs_alt
        if media.recorded_at is None:
            media.recorded_at = exif_dt

    elif kind == "subtitle":
        start, track, duration = parse_srt(path)
        media.duration_s = duration
        media.track = track
        if start:
            media.latitude = start.lat
            media.longitude = start.lon
            media.abs_alt = start.abs_alt

    elif kind == "video":
        drone, camera, header_gps, header_dt = scan_video_header(path)
        media.drone_model = drone
        media.camera_model = camera
        if header_gps:
            media.latitude = header_gps.lat
            media.longitude = header_gps.lon
            media.abs_alt = header_gps.abs_alt
        if media.recorded_at is None:
            media.recorded_at = header_dt

        # Prefer sibling SRT for GPS track / duration (DJI flights)
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
        else:
            # No SRT required: optional ffprobe for GPS / date / duration
            if media.latitude is None or media.recorded_at is None or media.duration_s is None:
                probe_gps, probe_dt, probe_dur = probe_video_with_ffprobe(path)
                if media.latitude is None and probe_gps:
                    media.latitude = probe_gps.lat
                    media.longitude = probe_gps.lon
                    media.abs_alt = probe_gps.abs_alt
                if media.recorded_at is None:
                    media.recorded_at = probe_dt
                if media.duration_s is None:
                    media.duration_s = probe_dur

    # Generic files: fall back to filesystem mtime when no DJI/EXIF/container date
    if kind in {"video", "photo"} and media.recorded_at is None:
        media.recorded_at = _file_mtime(path)

    if kind in {"video", "photo"}:
        media.source_type = classify_source_type(
            filename=path.name,
            mode=media.mode,
            drone_model=media.drone_model,
            camera_model=media.camera_model,
            make=media.exif_make,
        )

    return media
