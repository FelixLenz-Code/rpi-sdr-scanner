# RPi SDR Scanner

Kompakter Tischscanner im **1-DIN Autoradio-Format** auf Basis eines Raspberry Pi, eines RTL-SDR-Dongles und einem 3,5"-SPI-Touchscreen. Vorkonfigurierte Kanäle scannen, Memory-Bänke verwalten, manuell abstimmen — steuerbar über physische Tasten, einen Drehgeber oder ein Web-Interface per WLAN-Hotspot. Audio wahlweise über den lokalen 3,5-mm-Ausgang oder einen **Bluetooth-A2DP-Lautsprecher**.

---

## Hardware

| Komponente | Details |
|-----------|---------|
| SBC | Raspberry Pi 3B+ oder Zero 2 W |
| SDR-Dongle | NooElec NESDR SMArt v5 (RTL-SDR) |
| Display | MHS 3,5" IPS SPI (480×320, ILI9486-Controller, XPT2046-Touch) |

---

## Features

- **Kanalscanner** — scannt eine konfigurierbare Kanalliste, bleibt bei aktivem Signal stehen
- **Memory-Bänke** — 10 benannte Bänke, persistent in SQLite
- **Demodulationsmodi** — NFM, FM, WFM, AM (via `rtl_fm`)
- **Squelch-Regelung** — einstellbare Schwelle mit Hysterese, Signal-Balkenanzeige und 3 Schnell-Presets (Normal / Offen / Streng)
- **Monitor-Taste** — Squelch solange gedrückt halten zwangsweise öffnen (Mithören ohne Signal)
- **Bluetooth-Audio** — A2DP-Lautsprecher koppeln, verbinden und automatisch wiederherstellen; integrierter Wizard im Display-Menü
- **PPM-Kalibrierung** — integrierte Kalibrierung via `kalibrate-rtl`, Ergebnis wird automatisch gespeichert
- **Web-UI** — Vollzugriff per Flask + SSE auf `http://scanner.local:5000`
- **WLAN-Hotspot** — Pi als eigener Accesspoint (SSID: `SDR-Scanner`)
- **Touch-Menü** — Tippen auf die Hauptanzeige öffnet ein Schnellzugriffsmenü
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
├── start_scanner.sh         # Startscript für systemd (SDL/PA/BT-Umgebung)
├── config/
│   └── settings.py          # Alle Konfigurationswerte
├── core/
│   ├── scanner.py           # Haupt-Controller, Event-Loop, Zustandsmaschine
│   ├── frequency.py         # Kanalliste, Scan-Navigation
│   ├── squelch.py           # RSSI-Auswertung, Squelch-Logik
│   ├── demodulator.py       # rtl_fm Subprocess-Wrapper
│   ├── audio.py             # PCM → PulseAudio Pipeline
│   ├── bluetooth.py         # BlueZ/D-Bus Wrapper für BT-A2DP-Audio
│   ├── memory_banks.py      # 10 Memory-Bänke, SQLite-Persistenz
│   ├── bookmarks.py         # Empfangs-Log, DB-Verbindung
│   ├── buttons.py           # GPIO-Handler + ButtonEvent-Enum
│   └── calibration.py       # PPM-Kalibrierung via kalibrate-rtl
├── ui/
│   ├── display.py           # pygame Framebuffer-UI + Overlays + BT-Wizard
│   └── web.py               # Flask + SSE, REST-Endpunkte
├── hotspot/
│   ├── hotspot_start.sh     # Von systemd beim Boot aufgerufen
│   ├── hotspot_stop.sh
│   ├── change_wifi.sh       # SSID/Passwort per CLI ändern
│   └── fix_fstrim.sh        # Behebt fstrim-Boot-Hänger auf SD-Karten
```

---

## Verdrahtung

Alle Buttons und der Encoder liegen im **unteren Header-Block (Pins 29–40)** — konfliktfrei mit dem MHS/ILI9486 SPI-Display, das Pins 11–26 belegt.

### Buttons (Pull-Up, gegen GND schalten)

| Funktion | BCM | Phys. Pin | GND-Pin |
|----------|-----|-----------|---------|
| Monitor  | 16  | 36        | 39      |
| Mode     | 19  | 35        | 39      |
| Memory   | 20  | 38        | 39      |
| Squelch+ | 21  | 40        | 39      |
| Squelch− | 26  | 37        | 39      |

### Rotary Encoder

| Signal   | BCM | Phys. Pin | Hinweis |
|----------|-----|-----------|---------|
| VCC      | 12  | 32        | GPIO als 3,3V-Ausgang |
| A        | 5   | 29        | – |
| B        | 6   | 31        | – |
| SW (Taster) | 13 | 33     | – |
| GND      | –   | 30 / 34   | beide GND-Pins nutzbar |

### Display (MHS 3,5" SPI / ILI9486)

Direkter Aufsteck-Header (GPIO 7–11, 17, 18, 25, 27). Kompatibel mit dem `waveshare35a`-Kernel-Overlay (gleicher Chip + Pinout), wird von `install.sh` automatisch konfiguriert.

### RTL-SDR Dongle

Einfach per USB an den Pi anstecken. Bei Problemen mit dem Standard-DVB-Treiber:
```bash
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtl.conf
```

---

## Installation

### Voraussetzungen

- Raspberry Pi OS (Bookworm oder Bullseye) auf einer SD-Karte
- SSH-Zugang oder direkter Terminalzugriff auf dem Pi

### Option A – .deb-Paket (empfohlen)

Die einfachste Installationsmethode. Lädt das fertige Paket vom neuesten Release herunter und installiert es inkl. aller Abhängigkeiten.

```bash
# .deb herunterladen (Beispiel für v1.0.0)
wget https://github.com/FelixLenz-Code/rpi-sdr-scanner/releases/latest/download/sdr-scanner_1.0.0_arm64.deb

# Installieren
sudo dpkg -i sdr-scanner_1.0.0_arm64.deb

# Fehlende apt-Abhängigkeiten automatisch nachholen
sudo apt-get install -f
```

Nach der Installation startet der Scanner automatisch. Web-UI erreichbar unter **http://scanner.local:5000** (Hotspot `SDR-Scanner`, Passwort: `sdrscanner`).

### Option B – Repo klonen und Setup ausführen

```bash
git clone https://github.com/FelixLenz-Code/rpi-sdr-scanner.git
cd rpi-sdr-scanner
bash install.sh
```

`install.sh` installiert alle Abhängigkeiten (inkl. Bluetooth-Pakete), richtet den WLAN-Hotspot ein, installiert den systemd-Service und behebt den `fstrim`-Boot-Hänger.

**Optionen:**

```bash
bash install.sh --no-display     # Ohne SPI-Treiber (kein MHS-Display)
bash install.sh --no-hotspot     # Ohne Hotspot-Einrichtung
bash install.sh --no-service     # Ohne systemd-Service
bash install.sh --ssid NAME --pass PASS  # Hotspot nicht-interaktiv konfigurieren
```

---

## Starten

```bash
python3 main.py                    # Normal (SPI-Display, kein Web-UI)
python3 main.py --web              # Mit Web-UI auf http://192.168.4.1:5000
python3 main.py --hdmi             # HDMI-Fenster statt SPI (960×640)
python3 main.py --hdmi-size 1920x1080
python3 main.py --debug            # Kein GPIO, kein rtl_fm, kein Framebuffer
python3 main.py --no-display       # Nur Scanner-Kern + Web-UI
```

Wenn kein Display erkannt wird (`/dev/fb0`, `DISPLAY`, `WAYLAND_DISPLAY`), deaktiviert sich die Display-UI automatisch — Scanner und Web-UI laufen trotzdem.

Im systemd-Betrieb startet `start_scanner.sh` den Scanner: Es erkennt automatisch das richtige Framebuffer-Device (`fb_ili9486`), startet PulseAudio falls nötig und entsperrt Bluetooth-Adapter.

---

## Tastenbelegung

| Taste | Kurzer Druck | Langer Druck (≥ 0,8–1,5 s) |
|-------|-------------|---------------------------|
| **SCAN** (GPIO 16) | Monitor: Squelch öffnen solange gedrückt | — |
| **MODE** (GPIO 19) | Encoder-Modus wechseln (Kanal ↔ Lautstärke) | Demodulationsmodus wechseln (NFM → FM → WFM → AM) |
| **MEM** (GPIO 20) | Aktuellen Kanal in aktive Bank speichern | Bank-Auswahl öffnen |
| **SQ+** (GPIO 21) | Squelch +2 dBFS | — |
| **SQ−** (GPIO 26) | Squelch −2 dBFS | — |
| **Encoder drehen** | Kanal vor/zurück **oder** Lautstärke (je nach Encoder-Modus) | — |
| **Encoder drücken** | Scan starten / stoppen | Menü öffnen |

> **Encoder-Modus:** Ein kurzer Druck auf MODE schaltet um, ob der Encoder den Kanal oder die Lautstärke regelt. Der aktive Modus wird im Display angezeigt.

---

## Bluetooth-Audio

Der Scanner unterstützt A2DP-Lautsprecher (Bluetooth). Die Einrichtung erfolgt über den integrierten BT-Wizard im Display-Menü (Encoder lang drücken → „Bluetooth-Einrichtung").

**Ablauf:**
1. Menü öffnen → „Bluetooth-Einrichtung"
2. Bereits bekannte Geräte werden sofort angezeigt
3. „+ Neues Gerät" startet einen 10-Sekunden-Scan
4. Gerät auswählen → Verbinden → Audio-Sink wird automatisch auf BT umgestellt

**Auto-Reconnect:** Beim Systemstart verbindet sich der Scanner automatisch mit dem zuletzt gespeicherten Gerät (`BT_DEVICE_ADDRESS` in `config/settings.py`). Bei Verbindungsverlust versucht ein Hintergrundwatchdog alle 15 Sekunden neu zu verbinden.

**Konfiguration:**

```python
# config/settings.py
BT_DEVICE_ADDRESS  = "AA:BB:CC:DD:EE:FF"  # nach Pairing automatisch eingetragen
BT_AUTO_RECONNECT  = True
```

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
SQUELCH_DEFAULT    = -25      # dBFS-Startwert
SQUELCH_PRESETS    = [(-25, "Normal"), (-100, "Offen"), (-5, "Streng")]
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

**fstrim hängt den Boot** — SD-Karten implementieren TRIM oft fehlerhaft. Wird von `install.sh` automatisch behoben, oder manuell:
```bash
sudo bash hotspot/fix_fstrim.sh
```

**`kalibrate-rtl` nicht gefunden** — das Paket heißt je nach OS-Version `kalibrate-rtl` oder `kalibrate`. `install.sh` probiert beide.

**Display erscheint nicht als `/dev/fb1`** — ohne HDMI-Monitor könnte das SPI-Display als `/dev/fb0` erscheinen. `install.sh` setzt `hdmi_force_hotplug=1`, um das zu verhindern. `start_scanner.sh` erkennt das richtige fb-Device automatisch anhand des Treiber-Namens.

---

## systemd-Services

```bash
sudo systemctl status sdr_scanner
journalctl -u sdr_scanner -f
journalctl -u sdr_hotspot -f
```

---

## Hinweis zur KI-Unterstützung

Diese Software wurde vollständig mithilfe von Claude (einem KI-Assistenten von Anthropic) entwickelt. Der Autor hat die Anforderungen definiert, Entscheidungen getroffen und das Ergebnis geprüft — der Code selbst wurde durch den Dialog mit der KI generiert.

---

## Haftungsausschluss

Die Software wird so bereitgestellt, wie sie ist (as-is), ohne jegliche Garantie auf Korrektheit, Vollständigkeit oder Eignung für einen bestimmten Zweck. Der Autor übernimmt keinerlei Haftung für Schäden, Datenverluste oder sonstige Probleme, die durch die Verwendung dieser Software entstehen. Die Nutzung erfolgt auf eigene Verantwortung.

---

## Lizenz

[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — Namensnennung erforderlich, keine kommerzielle Nutzung.
