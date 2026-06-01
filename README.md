# RPi SDR Scanner

Kompakter Tischscanner im **1-DIN Autoradio-Format** auf Basis eines Raspberry Pi, eines RTL-SDR-Dongles und einem 3,5"-SPI-Touchscreen. Vorkonfigurierte Kanäle scannen, Memory-Bänke verwalten, manuell abstimmen — steuerbar über physische Tasten, einen Drehgeber oder ein Web-Interface per WLAN-Hotspot.

---

## Hardware

| Komponente | Details |
|-----------|---------|
| SBC | Raspberry Pi 3B+ oder Zero 2 W |
| SDR-Dongle | NooElec NESDR SMArt v5 (RTL-SDR) |
| Display | Waveshare 3,5" IPS SPI (480×320) |

---

## Features

- **Kanalscanner** — scannt eine konfigurierbare Kanalliste, bleibt bei aktivem Signal stehen
- **Memory-Bänke** — 10 benannte Bänke, persistent in SQLite
- **Demodulationsmodi** — NFM, FM, WFM, AM (direkte IQ-Demodulation via `pyrtlsdr` + numpy/scipy)
- **Squelch-Regelung** — einstellbare Schwelle mit Hysterese und Signal-Balkenanzeige
- **Monitor-Taste** — Squelch solange gedrückt halten zwangsweise öffnen (Mithören ohne Signal)
- **PPM-Kalibrierung** — integrierte Kalibrierung via `kalibrate-rtl`, Ergebnis wird automatisch gespeichert
- **Web-UI** — Vollzugriff per Flask + SSE auf `http://scanner.local:5000`
- **WLAN-Hotspot** — Pi als eigener Accesspoint (SSID: `SDR-Scanner`)
- **HDMI-Modus** — skalierbares Vorschaufenster zur Entwicklung ohne SPI-Display

---

## Screenshots

![Web-UI – Bank 1: FM Repeater](docs/screenshots/webui_bank1_fm_repeater.png)
*Web-Oberfläche mit Memory-Bank 1 „FM Repeater" (erreichbar über WLAN-Hotspot)*

---

## Projektstruktur

```
sdr_scanner/
├── main.py                  # Einstiegspunkt, CLI-Argumente
├── config/
│   └── settings.py          # Alle Konfigurationswerte
├── core/
│   ├── scanner.py           # Haupt-Controller, Event-Loop, Zustandsmaschine
│   ├── frequency.py         # Kanalliste, Scan-Navigation
│   ├── squelch.py           # RSSI-Auswertung, Squelch-Logik
│   ├── demodulator.py       # rtl_fm Subprocess-Wrapper
│   ├── audio.py             # PCM → PulseAudio/aplay Pipeline
│   ├── memory_banks.py      # 10 Memory-Bänke, SQLite-Persistenz
│   ├── bookmarks.py         # Empfangs-Log, DB-Verbindung
│   ├── buttons.py           # GPIO-Handler + ButtonEvent-Enum
│   └── calibration.py       # PPM-Kalibrierung via kalibrate-rtl
├── ui/
│   ├── display.py           # pygame Framebuffer-UI + Overlays
│   └── web.py               # Flask + SSE, REST-Endpunkte
├── hotspot/
│   ├── hotspot_start.sh     # Von systemd beim Boot aufgerufen
│   ├── hotspot_stop.sh
│   ├── change_wifi.sh       # SSID/Passwort per CLI ändern
│   └── fix_fstrim.sh        # Behebt fstrim-Boot-Hänger auf SD-Karten
```

---

## Installation

### Voraussetzungen

- Raspberry Pi OS (Bookworm oder Bullseye) auf einer SD-Karte
- SSH-Zugang oder direkter Terminalzugriff auf dem Pi

### Repo klonen und Setup ausführen

```bash
git clone https://github.com/FelixLenz-Code/rpi-sdr-scanner.git
cd rpi-sdr-scanner
bash setup.sh
```

`setup.sh` installiert alle Abhängigkeiten, richtet den WLAN-Hotspot ein, installiert den systemd-Service und behebt den `fstrim`-Boot-Hänger (häufiges Problem mit SD-Karten).

**Optionen:**

```bash
bash setup.sh --no-display     # Ohne Waveshare SPI-Treiber
bash setup.sh --no-hotspot     # Ohne Hotspot-Einrichtung
bash setup.sh --no-service     # Ohne systemd-Service
bash setup.sh --ssid NAME --pass PASS  # Hotspot nicht-interaktiv konfigurieren
```

---

## Starten

```bash
python3 main.py                    # Normal (SPI-Display, kein Web-UI)
python3 main.py --web              # Mit Web-UI auf http://192.168.4.1:5000
python3 main.py --hdmi             # HDMI-Fenster statt SPI (960×640) – noch ungetestet
python3 main.py --hdmi-size 1920x1080  # – noch ungetestet
python3 main.py --debug            # Kein GPIO, kein rtl_fm, kein Framebuffer
python3 main.py --no-display       # Nur Scanner-Kern + Web-UI
```

Wenn kein Display erkannt wird (`/dev/fb0`, `DISPLAY`, `WAYLAND_DISPLAY`), deaktiviert sich die Display-UI automatisch — Scanner und Web-UI laufen trotzdem.

---

## Tastenbelegung

| Taste | Kurzer Druck | Langer Druck (≥1 s) |
|-------|-------------|----------------------|
| **SCAN** (GPIO 17) | Monitor: Squelch öffnen solange gedrückt | — |
| **MODE** (GPIO 27) | — | Demodulationsmodus wechseln (NFM → FM → WFM → AM) |
| **MEM** (GPIO 22) | Bank-Auswahl öffnen | Aktuellen Kanal in aktive Bank speichern |
| **SQ+** (GPIO 23) | Squelch +2 dBFS | — |
| **SQ−** (GPIO 24) | Squelch −2 dBFS | — |
| **Encoder drehen** | Kanal vor/zurück (Idle) · Lautstärke (Scan) | — |
| **Encoder drücken** | Scan starten / stoppen | Menü öffnen |

---

## Kanäle konfigurieren

In `config/settings.py`:

```python
CHANNELS = [
    {"name": "Feuerwehr 1",  "freq": 155_800_000, "mode": "NFM", "group": "BOS"},
    {"name": "PMR Kanal 1",  "freq": 446_006_250, "mode": "NFM", "group": "PMR"},
    {"name": "UKW Radio",    "freq": 100_300_000, "mode": "WFM", "group": "FM"},
]
```

Kanäle lassen sich auch zur Laufzeit über das Web-UI oder die MEM-Taste hinzufügen und bearbeiten.

Wichtige Einstellungen:

```python
RTL_DEVICE_INDEX   = 0        # SDR-Dongle-Index
RTL_PPM_CORRECTION = 0        # Nach Kalibrierung setzen, z.B. -7
RTL_GAIN           = "auto"
SCAN_DWELL_TIME    = 0.15     # Sekunden pro Kanal beim Scan
SQUELCH_DEFAULT    = -60      # dBFS-Schwelle
```

---

## Web-UI

Mit `--web` gestartet, stellt der Scanner eine REST + SSE-Schnittstelle auf Port 5000 bereit.

| Endpunkt | Funktion |
|----------|----------|
| `GET /` | HTML-Bedienoberfläche |
| `GET /events` | SSE Live-Status-Stream |
| `GET /channels` | Kanalliste |
| `POST /cmd/<action>` | Button-Event auslösen (z.B. `SCAN_TOGGLE`) |
| `POST /tune/<index>` | Auf Kanal abstimmen |
| `POST /tune/freq` | Direkte Frequenz `{freq, mode}` |
| `POST /set/squelch` | Squelch setzen `{level}` |
| `POST /set/volume` | Lautstärke setzen `{volume}` |
| `POST /bank/load/<id>` | Memory-Bank wechseln |
| `POST /rename/current` | Aktiven Kanal umbenennen `{name}` |

Alle 21 Endpunkte in `ui/web.py`.

---

## WLAN-Hotspot

Der Pi erstellt beim Hochfahren einen eigenen Accesspoint:

| | Standard |
|-|----------|
| SSID | `SDR-Scanner` |
| Passwort | `sdrscanner` |
| Pi-IP | `192.168.4.1` |
| Web-UI | `http://scanner.local:5000` oder `http://192.168.4.1:5000` |

SSID/Passwort ändern:

```bash
sudo bash hotspot/change_wifi.sh "MeinScanner" "neuespasswort"
```

---

## Bekannte Probleme

**fstrim hängt den Boot** — SD-Karten implementieren TRIM oft fehlerhaft. Wird von `setup.sh` automatisch behoben, oder manuell:
```bash
sudo bash hotspot/fix_fstrim.sh
```

**`kalibrate-rtl` nicht gefunden** — das Paket heißt je nach OS-Version `kalibrate-rtl` oder `kalibrate`. `setup.sh` probiert beide.

---

## systemd-Services

```bash
sudo systemctl status sdr_scanner
journalctl -u sdr_scanner -f
journalctl -u sdr_hotspot -f
```

---

## Lizenz

MIT
