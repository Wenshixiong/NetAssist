<div align="center">

# NetAssist Network Operations Tool

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Flask](https://img.shields.io/badge/Flask-3.1.2-green)
![License](https://img.shields.io/badge/License-Apache%202.0-orange)
![Version](https://img.shields.io/badge/Version-v1.5.2-brightgreen)

**A local operations toolkit for network engineers: device asset analytics, LLDP-based auto topology, multi-scenario batch script generation, and text diff.**

[Repository](https://github.com/Wenshixiong/NetAssist) · [QQ Group: 1098907087](https://qm.qq.com/q/1098907087) · Email: 1205244490@qq.com

[中文](README.md)

</div>

---

## Features

### Information Charts
Automatically aggregates and visualizes data from the device maintenance Excel:
- **Maintenance Status**: No warranty / Expired / Expiring soon (within 6 months) / Active — with one-click Excel export of details
- **EOS Status**: End of support / Ending soon (within 2 years) / In service / No EOS info — with Excel export
- **Device Distribution**: Multi-dimensional breakdown by data center, business zone, vendor, and device model
- **Interactive Filtering**: Cross-filter by model and business zone
- Auto-excludes decommissioned devices (red-highlighted rows) and line-card models (CE- / CEL / CR prefixes)

### Network Topology
Renders LLDP-derived device interconnection data with Cytoscape.js:
- **Global Topology**: Full architecture view with drag, zoom, and hover tooltips (model / IP / serial / MAC / vendor / zone)
- **Zone Topology**: Per-business-zone view with auto-filtered devices and links
- **Coordinate Persistence**: Dragged node positions are written back to Excel and restored on next launch
- Export topology as PNG

### Batch Script Generation
Plugin-based architecture that generates **change scripts + rollback scripts** from Excel data. Five built-in scenarios:

| Scenario Module | Description |
|---|---|
| CE Baseline & L2 | Switch base config + Layer 2 services, MLAG template support |
| CE L3 | Switch Layer 3 interface / routing config |
| CE Static Route | Bulk static route provisioning |
| FW Virtual System | Firewall virtual system (vsys) configuration |
| L3GW Custom Cloud Line | Bulk custom cloud leased-line generation |

- Upload / download / preview / delete template files, data source Excel, device name mapping tables, and custom line files
- Generated scripts available as individual downloads or full ZIP archive

### Sorted Text Diff
- Sorts two text inputs independently and compares differences (diff.js)
- Quickly spot discrepancies between config files or command outputs

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 · Flask 3.1 · waitress (production WSGI) |
| GUI Launcher | tkinter · pystray (system tray) |
| Data Processing | pandas · openpyxl · python-dateutil |
| System Monitoring | psutil |
| Frontend | Tailwind CSS · ECharts · Cytoscape.js · Font Awesome |
| Packaging | PyInstaller (`--onefile` single executable) |

---

## Quick Start

### Requirements
- Python 3.11 (development and test environment)
- Windows / macOS / Linux (GUI launcher and tray work best on Windows)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Launch

**Option 1: GUI Launcher (recommended)**

```bash
python launch_v1.5.2.py
```

A graphical manager opens for port configuration, cache strategy selection, and log viewing, with system tray minimization. Click "Start Service" then visit `http://127.0.0.1:5001`.

**Option 2: Direct Web Server**

```bash
python NetAssist_v1.5.2.py
```

Listens on `0.0.0.0:5001` by default.

### Cache Strategy

| Strategy | Environment Variables | Description |
|---|---|---|
| Full preload (default) | `NETASSIST_PRELOAD=true` `NETASSIST_USE_CACHE=true` | Preload all stats at startup for instant charts |
| Debug mode | `NETASSIST_PRELOAD=false` `NETASSIST_USE_CACHE=false` | Real-time computation per request, DEBUG logging enabled |

Use the `/refresh_cache` endpoint to refresh a specific cache key on demand.

---

## Project Structure

```
NetAssist/
├── NetAssist_v1.5.2.py      # Flask main application
├── launch_v1.5.2.py         # tkinter GUI launcher + system tray
├── version.py               # Version metadata (single source of truth)
├── bump_version.py          # Version bump helper
├── requirements.txt         # Python dependencies
├── 打包命令.txt               # PyInstaller build command reference
├── LICENSE                  # Apache 2.0
├── RELEASE.md               # Release notes
├── html/                    # Jinja2 templates
│   ├── base.html            # Layout skeleton (sidebar nav)
│   ├── index.html           # Home page
│   ├── about.html           # About (with full license text)
│   ├── info_chart.html      # Information charts
│   ├── topology/            # Global / zone topology
│   └── work/                # File manager / scenario gen / text diff
├── static/
│   ├── css/output.css       # Tailwind build output
│   ├── css/topology_tooltips.css
│   ├── js/                  # ECharts / Cytoscape / diff / html-to-image
│   ├── fontawesome-free/    # Icon library (CSS + webfonts)
│   ├── icons/               # App icons and device-type icons
│   └── TailwindCSS_CLI/     # Tailwind build env (package.json + config)
├── imported_mods/           # Plugin script-generation modules (5 scenarios)
├── asset_info/              # Asset data (device list / LLDP table / name mapping)
├── data_uploads/            # Script generation data source Excel (uploadable)
│   └── custom_line_uploads/ # Custom cloud line files
├── templates_uploads/       # Script template files (uploadable)
└── generated_scripts/       # Script output directory (auto-created at runtime)
```

---

## Data Files

On startup the app validates two core Excel files under `asset_info/` and exits if either is missing. Override the filenames via `asset_info/设备清单及拓扑映射表_示例.txt`:

```ini
EXCEL_FILENAME=设备维护清单.xlsx
LLDP_FILENAME=设备信息及互联表.xlsx
```

### Device Maintenance List.xlsx
| Sheet | Purpose | Key Columns |
|---|---|---|
| Device List | Master asset table | Device model, data center, business zone, warranty start/end, serial, management IP |
| Device EOS Info | Model → EOS date mapping | Device model, EOS date |
| Other Vendor Device Count | Vendor-level device count summary | Vendor, Count |

> Red-highlighted rows are treated as decommissioned and excluded; `CE-` / `CEL` / `CR` prefixes are treated as line cards and excluded.

### Device Info & Interconnection Table.xlsx (LLDP)
| Sheet | Purpose | Key Columns |
|---|---|---|
| Device Base Info | Static device info | Device name, zone, data center, serial SN, MAC, model, management IP, show in global topology |
| Device Zone Coordinates | Topology node positions | Device name, current zone, topology_x, topology_y |
| Device Zone Interconnection | Device links | Zone, local device, local interface, remote device, remote interface |

---

## Style Development (Tailwind CSS)

The project uses the Tailwind CSS CLI. Sources live in `static/TailwindCSS_CLI/`:

```bash
cd static/TailwindCSS_CLI
npm install          # First-time setup (single dependency: tailwindcss)
npx tailwindcss -i ./src/input.css -o ../css/output.css --watch
```

- Input: `src/input.css` (includes custom utilities `sidebar-active`, `nav-item-hover`)
- Output: `static/css/output.css`
- Scan scope: `../js/*.js` and `../../html/**/*.html` (configured in `tailwind.config.js`)
- In `--watch` mode, new Tailwind classes in HTML trigger an automatic rebuild

---

## Build as exe

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --name "NetAssist_v1.5.2" --icon="static/icons/NetAssist_64.ico" ^
    --add-data "asset_info;asset_info" ^
    --add-data "html;html" ^
    --add-data "templates_uploads;templates_uploads" ^
    --add-data "data_uploads;data_uploads" ^
    --add-data "imported_mods;imported_mods" ^
    --add-data "static/css;static/css" ^
    --add-data "static/icons;static/icons" ^
    --add-data "static/js;static/js" ^
    --add-data "static/fontawesome-free;static/fontawesome-free" ^
    launch_v1.5.2.py
```

On first launch, `ensure_resources_once()` copies sample Excel files and templates from inside the exe to the exe's directory.

---

## Development

### Version Management
`version.py` is the single source of truth. Use `bump_version.py` to increment and auto-rename the main and launcher files:

```bash
python bump_version.py              # 1.5.2 -> 1.5.3 (patch)
python bump_version.py --minor      # 1.5.3 -> 1.6.0
python bump_version.py --major      # 1.6.0 -> 2.0.0
python bump_version.py --set 2.1.0  # Explicit set
```

### Adding a Script Generation Scenario
1. Create a module in `imported_mods/` exposing `main(EXCEL_NAME, SHEET_NAME, OUTPUT_DIR, ROLLBACK_DIR, ...)`
2. Load it dynamically in `NetAssist_v1.5.2.py` via `load_module_from_path()`
3. Dispatch by data-source filename keyword in the `/generate_scripts` route

### Environment Variables
| Variable | Default | Description |
|---|---|---|
| `FLASK_SECRET_KEY` | `dev_secret_key_should_be_changed` | Flask session secret — change in production |
| `NETASSIST_PRELOAD` | `true` | Preload stats cache at startup |
| `NETASSIST_USE_CACHE` | `true` | Use cache for requests |
| `NETASSIST_DEBUG` | `false` | Enable DEBUG-level logging |

---

## License

Licensed under the [Apache License 2.0](LICENSE), Copyright © 2026 Wenshixiong/NetAssist.
