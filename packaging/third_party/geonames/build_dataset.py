"""Build the reverse-geocoder CSV from the archived GeoNames dump.

The column mapping matches reverse_geocoder 1.5.1 ``RGeocoder.extract``.
"""

from __future__ import annotations

import csv
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "upstream"
OUTPUT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "orga_drone"
    / "geocode"
    / "rg_cities1000.csv"
)

RG_COLUMNS = ["lat", "lon", "name", "admin1", "admin2", "cc"]
GN_LAT = 4
GN_LON = 5
GN_CC = 8
GN_ADMIN1 = 10
GN_ADMIN2 = 11
GN_ASCII = 2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build() -> Path:
    with zipfile.ZipFile(UPSTREAM / "cities1000.zip") as archive:
        raw = archive.read("cities1000.txt")
    admin1: dict[str, str] = {}
    for row in csv.reader((UPSTREAM / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines(), delimiter="\t"):
        if len(row) > 2:
            admin1[row[0]] = row[2]
    admin2: dict[str, str] = {}
    for row in csv.reader((UPSTREAM / "admin2Codes.txt").read_text(encoding="utf-8").splitlines(), delimiter="\t"):
        if len(row) > 2:
            admin2[row[0]] = row[2]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=RG_COLUMNS)
        writer.writeheader()
        for line in raw.decode("utf-8").splitlines():
            row = next(csv.reader([line], delimiter="\t", quoting=csv.QUOTE_NONE))
            cc = row[GN_CC]
            admin1_code = cc + "." + row[GN_ADMIN1]
            admin2_code = admin1_code + "." + row[GN_ADMIN2]
            writer.writerow(
                {
                    "lat": row[GN_LAT],
                    "lon": row[GN_LON],
                    "name": row[GN_ASCII],
                    "admin1": admin1.get(admin1_code, ""),
                    "admin2": admin2.get(admin2_code, ""),
                    "cc": cc,
                }
            )
            count += 1
    provenance = ROOT / "PROVENANCE.txt"
    lines = [
        "GeoNames gazetteer extract retrieved 2026-10-26 from",
        "https://download.geonames.org/export/dump/",
        "readme.txt in this directory states Creative Commons Attribution 4.0.",
        "https://creativecommons.org/licenses/by/4.0/",
        "The formatted CSV uses the reverse_geocoder 1.5.1 column mapping.",
        f"rows {count}",
        "",
    ]
    for name in ("cities1000.zip", "admin1CodesASCII.txt", "admin2Codes.txt", "readme.txt"):
        path = UPSTREAM / name
        lines.append(f"{_sha256(path)}  upstream/{name}  {path.stat().st_size}")
    lines.append(f"{_sha256(OUTPUT)}  src/orga_drone/geocode/rg_cities1000.csv  {OUTPUT.stat().st_size}")
    provenance.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"rows {count}")
    print(provenance)
    return OUTPUT


if __name__ == "__main__":
    build()
