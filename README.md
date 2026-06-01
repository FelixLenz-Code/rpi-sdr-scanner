# RPi SDR Scanner

Tischscanner auf Basis Raspberry Pi 4B + NooElec NESDR SMArt v5.

## Projektstruktur

```
sdr_scanner/
├── main.py               # Einstiegspunkt, Event-Loop
├── config/
│   └── settings.py       # Alle Einstellungen zentral
├── core/
│   ├── scanner.py        # Scanner-Daemon (Hauptlogik)
│   ├── frequency.py      # Frequency Manager + Kanalverwaltung
│   ├── squelch.py        # Squelch Controller
│   ├── demodulator.py    # rtl_fm Subprocess-Wrapper
│   ├── audio.py          # Audio-Pipeline
│   ├── bookmarks.py      # SQLite Bookmarks & Logging
│   └── buttons.py        # GPIO Button Handler
└── ui/
    ├── display.py        # pygame Display-UI (Framebuffer)
    └── web.py            # Flask Web-UI (optional)
```

## Installation

```bash
# System-Pakete
sudo apt update
sudo apt install -y rtl-sdr python3-pip python3-pygame python3-flask \
    python3-gpiozero pulseaudio libportaudio2

# Python-Pakete
pip3 install gpiozero RPi.GPIO flask flask-sock

# RTL-SDR Blacklist (damit der Standard-DVB-Treiber nicht lädt)
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtl.conf

# Service installieren
sudo cp sdr_scanner.service /etc/systemd/system/
sudo systemctl enable sdr_scanner
sudo systemctl start sdr_scanner
```

## Starten (manuell)

```bash
# Nur Display-UI
python3 main.py

# Mit Web-UI (erreichbar auf http://<pi-ip>:5000)
python3 main.py --web

# HDMI-Vorschau (kein SPI-Display nötig, skalierbares Fenster)
python3 main.py --hdmi

# HDMI mit eigener Auflösung
python3 main.py --hdmi --hdmi-size 1280x853

# Debug-Modus (kein echtes Display, Ausgabe auf stdout)
python3 main.py --debug
```

## Tasten-Belegung (GPIO)

| GPIO | Funktion        |
|------|-----------------|
| 17   | Scan Start/Stop |
| 27   | Mode wechseln   |
| 22   | Memory speichern|
| 23   | Squelch +       |
| 24   | Squelch -       |
| Enc A/B | Frequenz/Vol |
| Enc SW  | Enter/Select |

## Frequenzen konfigurieren

Kanäle in `config/settings.py` unter `CHANNELS` eintragen oder
zur Laufzeit über das Menü hinzufügen (werden in `bookmarks.db` gespeichert).
