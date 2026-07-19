# orga-drone

Local open-source **drone video library** manager. Built first for **DJI Avata 2**, works on Windows (primary), macOS, and Linux.

Your media stays on your machine. No cloud account is required for the MVP.

## Features (MVP)

- Index one or more folders / drives into a single library
- List videos and photos by **date**, **size**, **duration**, **drone**, **GPS**, **flow**
- Detect **drone model** from DJI MP4 metadata / photo EXIF (`FC8485` → DJI Avata 2)
- Read **GPS** from DJI `.SRT` telemetry and photo EXIF
- Group **split clips** (≈4 GB FAT32 splits) into a **flow**
- Show location on an embedded **OpenStreetMap** map (Leaflet) + external OSM link
- UI in **German** and **English** (JSON + `.po` i18n files for future languages)
- **Rename** files (and matching LRF/SRT siblings) from the detail page
- **Auto-merge** split flow clips into one MP4 (via bundled/`imageio-ffmpeg` or system `ffmpeg`; originals kept)

## Requirements

- Python **3.11+**
- Optional: network access for OSM map tiles (library itself works offline)

## Install (Python application)

```bash
git clone https://github.com/YOUR_USER/orga-drone.git
cd orga-drone
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

Copy environment defaults if you want:

```bash
cp .env.example .env
```

Do **not** put passwords or API keys in the repo. The app does not need them for local use.

## Run

```bash
python -m orga_drone
```

Or:

```bash
orga-drone
```

Then open `http://127.0.0.1:8765/` (the browser may open automatically).

### Add your media

1. Open **Library**
2. Paste a folder path (example only — use your own path):
   - Windows: `D:\DroneMedia`
   - macOS/Linux: `/media/user/drone`
3. Click **Add folder** (scans immediately)
4. Browse, filter, and open details / map

App data (SQLite index) is stored in the OS app-data folder, e.g.:

- Windows: `%APPDATA%\orga-drone\`
- macOS: `~/Library/Application Support/orga-drone/`
- Linux: `~/.local/share/orga-drone/`

Override with `ORGA_DRONE_DATA_DIR` in `.env`.

## Distribution

| Channel | Audience | Status |
|---------|----------|--------|
| **Python app** (this repo) | Developers / power users | Available now |
| **Prebuilt downloads** (GitHub Releases, e.g. Windows `.exe` via PyInstaller) | End users without Python | Planned next — see [`packaging/README.md`](packaging/README.md) |

Prebuilt binaries will ship **only the application**, never your videos or database.

## DJI notes

Typical Avata 2 filenames:

```text
DJI_YYYYMMDDHHMMSS_NNNN_D.MP4
DJI_YYYYMMDDHHMMSS_NNNN_D.LRF   # proxy
DJI_YYYYMMDDHHMMSS_NNNN_D.SRT   # telemetry (GPS, altitude, …)
DJI_YYYYMMDDHHMMSS_NNNN_D.JPG
```

Long recordings are often split near ~3.5 GB. orga-drone groups those consecutive parts into one **flow**.

## Roadmap (not in MVP)

- Spot export (GeoJSON) and optional community sharing of flight spots
- Reverse geocoding (place names)
- Video/LRF preview player
- Auto-merge of split files
- More drone brands via parsers
- CI-built installers for Windows / macOS / Linux

## Development

```bash
pip install -e ".[dev]"
python -m orga_drone
```

## License

MIT — see [LICENSE](LICENSE).
