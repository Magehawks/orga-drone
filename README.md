# orga-drone

Local open-source **drone video library** manager. Built first for **DJI Avata 2**, works on Windows (primary), macOS, and Linux.

Your media stays on your machine. No cloud account is required for the MVP.

## Features (MVP)

- Index one or more folders / drives into a single library
- List videos and photos by **date**, **size**, **duration**, **drone**, **GPS**, **flow**
- Detect **drone model** from DJI MP4 metadata / photo EXIF (`FC8485` → DJI Avata 2)
- Read **GPS** from DJI `.SRT` telemetry and photo EXIF
- Group **split clips** (≈4 GB FAT32 splits) into a **flow**
- Group a logical **flight session** (takeoff → landing) across one or more clips/flows
- Show location on an embedded **OpenStreetMap** map (Leaflet) + external OSM link
- UI in **German** and **English** (JSON + `.po` i18n files for future languages)
- **Themes**: Dark, Light, and Custom (accent / background / panel) — choice persisted via cookie + `%APPDATA%/orga-drone/theme.json`
- **Rename** files (and matching LRF/SRT siblings) from the detail page
- **Auto-merge** split flow clips into one MP4 (via bundled/`imageio-ffmpeg` or system `ffmpeg`; originals kept)
- **Spot export** (GeoJSON / `.orga-spot.json`) from the detail page when GPS is available — **local download only**, no upload

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

### Themes

In the header, switch **Dark** / **Light** / **Custom**. Custom shows color pickers for accent, background, and panel; click **Apply** to save. Preference is stored in a cookie and mirrored to `theme.json` in the app-data folder (not in the git repo).

### Spot export (GeoJSON)

On a detail page with GPS, use **Export spot** / **Spot exportieren**. The browser downloads a `.orga-spot.json` GeoJSON file (also available at `GET /media/{id}/export/spot.geojson`).

- **Local only** — nothing is uploaded; files stay on your machine.
- Coordinates are rounded to **4 decimal places** (≈11 m) so the exact home/takeoff point is not exported.
- Optional flight track is included as a simplified LineString when SRT telemetry exists.
- Future **community sharing** of flight spots will be opt-in and separate from this local export.

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

### Sessions vs Flows

| | **Flow** | **Session** |
|---|----------|-------------|
| Meaning | One continuous recording split by the camera/filesystem (FAT32 ≈4 GB parts) | One logical flight from takeoff to landing |
| Typical size | 2+ consecutive near-full files with tiny gaps | One or more clips/flows with short idle gaps |
| Detection | File size near limit + sequence/time | Time gaps + optional SRT altitude/GPS (near ground = landing) |
| UI | Badge “N parts”; filter “Only multi-clip flows” | Badge “N clips”; filter “Only multi-clip sessions”; detail lists all session clips |

Flows nest inside sessions: split parts of the same recording always share one session. After each library scan, flows are rebuilt first, then sessions.

## Roadmap (not in MVP)

- Optional community sharing of flight spots (opt-in; builds on local GeoJSON export)
- Reverse geocoding (place names)
- More drone brands via parsers
- CI-built installers for Windows / macOS / Linux

## Development

```bash
pip install -e ".[dev]"
python -m orga_drone
```

## License

MIT — see [LICENSE](LICENSE).
