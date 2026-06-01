# RPi SDR Scanner

A compact desktop scanner in **1-DIN car radio format** (180 × 50 × 170 mm) built around a Raspberry Pi, an RTL-SDR dongle, and a 3.5" SPI touchscreen. Scan preconfigured channels, manage memory banks, tune manually, and control everything via physical buttons, a rotary encoder, or a web interface over Wi-Fi hotspot.

---

## Hardware

| Component | Details |
|-----------|---------|
| SBC | Raspberry Pi 3B+ or Zero 2 W |
| SDR Dongle | NooElec NESDR SMArt v5 (RTL-SDR) |
| Display | Waveshare 3.5" IPS SPI (480×320) |
| Case | 3D-printed PETG, 2-part (base + lid) |

---

## Features

- **Channel scanner** — scans a configurable channel list, stops on active signals
- **Memory banks** — 10 named banks, persistent in SQLite
- **Demodulation modes** — NFM, FM, WFM, AM (via `rtl_fm`)
- **Squelch control** — adjustable threshold with hysteresis, signal bar display
- **Monitor button** — force-opens squelch while held (listen without signal)
- **PPM calibration** — built-in calibration via `kalibrate-rtl`, auto-saves result
- **Web UI** — full control via Flask + SSE at `http://scanner.local:5000`
- **Wi-Fi hotspot** — Pi acts as its own access point (SSID: `SDR-Scanner`)
- **HDMI mode** — scaled preview window for development without SPI display

---

## Project Structure

```
sdr_scanner/
├── main.py                  # Entry point, CLI arguments
├── config/
│   └── settings.py          # All configuration values
├── core/
│   ├── scanner.py           # Main controller, event loop, state machine
│   ├── frequency.py         # Channel list, scan navigation
│   ├── squelch.py           # RSSI evaluation, squelch logic
│   ├── demodulator.py       # rtl_fm subprocess wrapper
│   ├── audio.py             # PCM → PulseAudio/aplay pipeline
│   ├── memory_banks.py      # 10 memory banks, SQLite persistence
│   ├── bookmarks.py         # Reception log, DB connection
│   ├── buttons.py           # GPIO handler + ButtonEvent enum
│   └── calibration.py       # PPM calibration via kalibrate-rtl
├── ui/
│   ├── display.py           # pygame framebuffer UI + overlays
│   └── web.py               # Flask + SSE, REST endpoints
├── hotspot/
│   ├── hotspot_start.sh     # Called by systemd on boot
│   ├── hotspot_stop.sh
│   ├── change_wifi.sh       # CLI tool to change SSID/password
│   └── fix_fstrim.sh        # Fixes fstrim boot hang on SD cards
└── case/
    ├── case_params.scad     # All dimensions — included by both parts
    ├── scanner_base.scad    # Bottom shell + integrated front panel
    ├── scanner_lid.scad     # Lid (printed upside down)
    └── scanner_assembly.scad
```

---

## Installation

### Recommended: automated setup

```bash
# Transfer the project to your Pi
scp -r sdr_scanner/ pi@<pi-ip>:/home/pi/
ssh pi@<pi-ip>

# Run the setup script
cd /home/pi/sdr_scanner
bash setup.sh
```

`setup.sh` installs all dependencies, configures the Wi-Fi hotspot, installs the systemd service, and masks `fstrim` (which hangs on SD cards).

**Options:**

```bash
bash setup.sh --no-display     # Skip Waveshare SPI driver
bash setup.sh --no-hotspot     # Skip hotspot setup
bash setup.sh --no-service     # Skip systemd service
bash setup.sh --ssid NAME --pass PASS  # Non-interactive hotspot config
```

### SD card auto-install (firstrun.sh)

Copy `firstrun.sh` and `sdr_scanner.zip` to the boot partition, then append to `cmdline.txt`:

```
systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=reboot
```

The Pi installs everything automatically on first boot.

---

## Running

```bash
python3 main.py                    # Normal (SPI display, no web UI)
python3 main.py --web              # With web UI at http://192.168.4.1:5000
python3 main.py --hdmi             # HDMI window instead of SPI (960×640)
python3 main.py --hdmi-size 1920x1080
python3 main.py --debug            # No GPIO, no rtl_fm, no framebuffer
python3 main.py --no-display       # Scanner core + web UI only
```

If no display is detected (`/dev/fb0`, `DISPLAY`, `WAYLAND_DISPLAY`), the display UI is disabled automatically and the scanner keeps running.

---

## Button Layout

| Button | Short press | Long press (≥1 s) |
|--------|-------------|-------------------|
| **SCAN** (GPIO 17) | Monitor: hold to force-open squelch | — |
| **MODE** (GPIO 27) | — | Cycle demodulation mode (NFM → FM → WFM → AM) |
| **MEM** (GPIO 22) | Open bank selector | Save current channel to active bank |
| **SQ+** (GPIO 23) | Squelch +2 dBFS | — |
| **SQ−** (GPIO 24) | Squelch −2 dBFS | — |
| **Encoder turn** | Next/previous channel (idle) · Volume (scanning) | — |
| **Encoder press** | Scan start / stop | Open menu |

---

## Channel Configuration

Edit `config/settings.py`:

```python
CHANNELS = [
    {"name": "Fire Dept 1",  "freq": 155_800_000, "mode": "NFM", "group": "BOS"},
    {"name": "PMR Ch 1",     "freq": 446_006_250, "mode": "NFM", "group": "PMR"},
    {"name": "WFM Radio",    "freq": 100_300_000, "mode": "WFM", "group": "FM"},
]
```

Channels can also be added/edited at runtime via the web UI or the MEM button.

Key settings:

```python
RTL_DEVICE_INDEX   = 0        # SDR dongle index
RTL_PPM_CORRECTION = 0        # Set after calibration, e.g. -7
RTL_GAIN           = "auto"
SCAN_DWELL_TIME    = 0.15     # Seconds per channel while scanning
SQUELCH_DEFAULT    = -60      # dBFS threshold
```

---

## Web UI

When started with `--web`, the scanner exposes a full REST + SSE interface at port 5000.

| Endpoint | Function |
|----------|----------|
| `GET /` | HTML control panel |
| `GET /events` | SSE live status stream |
| `GET /channels` | Channel list |
| `POST /cmd/<action>` | Trigger any button event (e.g. `SCAN_TOGGLE`) |
| `POST /tune/<index>` | Tune to a channel |
| `POST /tune/freq` | Tune to a raw frequency `{freq, mode}` |
| `POST /set/squelch` | Set squelch level `{level}` |
| `POST /set/volume` | Set volume `{volume}` |
| `POST /bank/load/<id>` | Switch memory bank |
| `POST /rename/current` | Rename active channel `{name}` |

Full endpoint list in `ui/web.py`.

---

## Wi-Fi Hotspot

The Pi creates its own access point on boot:

| | Default |
|-|---------|
| SSID | `SDR-Scanner` |
| Password | `sdrscanner` |
| Pi IP | `192.168.4.1` |
| Web UI | `http://scanner.local:5000` or `http://192.168.4.1:5000` |

Change SSID/password:

```bash
sudo bash hotspot/change_wifi.sh "MyScanner" "newpassword"
```

---

## 3D-Printed Case

All dimensions are in `case/case_params.scad` and included by both part files.

- **Base** (`scanner_base.scad`): bottom shell with integrated front panel — print as one part
- **Lid** (`scanner_lid.scad`): print upside down for a smooth top surface
- **Mounting**: 4× M2.5 countersunk screws into heat inserts
- **RPi 3B+**: `ZERO_HOLE_DX=58`, `ZERO_HOLE_DY=49`
- **RPi Zero 2 W**: `ZERO_HOLE_DX=58`, `ZERO_HOLE_DY=23`

Export STLs in OpenSCAD with F6, then slice individually.

---

## Known Issues

**fstrim hangs on boot** — SD cards often implement TRIM incorrectly. Fixed automatically by `setup.sh`, or manually:
```bash
sudo bash hotspot/fix_fstrim.sh
```

**`kalibrate-rtl` not found** — the package is called `kalibrate-rtl` or `kalibrate` depending on OS version. `setup.sh` tries both.

---

## systemd Services

```bash
sudo systemctl status sdr_scanner
journalctl -u sdr_scanner -f
journalctl -u sdr_hotspot -f
```

---

## License

MIT
