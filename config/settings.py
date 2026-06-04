# config/settings.py
# Zentrale Konfiguration – hier alles anpassen

# ── RTL-SDR Hardware ──────────────────────────────────────────────────────────
RTL_DEVICE_INDEX = 0          # Falls mehrere SDR-Dongles: 0, 1, 2 ...
RTL_GAIN = "300"              # Zehntel-dB: 300 = 30 dB. "auto" führt zu zu hohem Rauschen
RTL_PPM_CORRECTION = 0        # Frequenzkorrektur in ppm (mit kalibr. Tool ermitteln)
RTL_SAMPLE_RATE = 250000      # Sample-Rate Hz (250000 = 250 kSps)

# ── Audio ─────────────────────────────────────────────────────────────────────
AUDIO_RATE = 48000            # Ausgabe-Samplerate Hz
AUDIO_DEVICE = "default"      # PulseAudio-Gerät ("default" reicht meistens)
VOLUME_DEFAULT = 70           # Lautstärke 0–100 beim Start
AUDIO_SOFT_GAIN = 20.0        # Software-PCM-Verstärkung nach FM-Demodulation.
AUDIO_GATE_THRESHOLD = 600    # Audio-Noise-Gate: RMS-Schwelle nach Gain-Anwendung.
                              # 0 = deaktiviert. Rauschen (niedriges RMS) wird quadratisch
                              # gedämpft, Stimme (höheres RMS) passiert unverändert.
                              # Richtwert NFM: 300–1000 je nach Empfangspegel ausprobieren.

AUDIO_COMP_THRESHOLD = 4000   # Kompressor-Einsatzschwelle (RMS nach Gain). 0 = aus.
AUDIO_COMP_RATIO     = 4.0    # Kompressionsverhältnis (z.B. 4.0 = 4:1).
                              # Über der Schwelle gilt: gain = (thr/env)^(1-1/ratio)
AUDIO_AGC_MAKEUP     = 2.5    # Zusätzlicher Software-Gain wenn RTL-Hardware-AGC aktiv ist.
                              # AGC wählt oft niedrigere Hardware-Verstärkung → ausgleichen.
                              # Bei zu laut: kleiner (z.B. 1.8), bei zu leise: größer (z.B. 3.5).
AUDIO_COMP_MAKEUP    = 1.8    # Makeup-Gain nach Kompression: hebt leise Stellen an.
                              # NFM-Hub ±2,5 kHz bei 240 kHz Abtastrate ergibt nur ~2 %
                              # Aussteuerung → ×20 bringt auf ~40 % (≈ gute Sprachlautstärke).

# ── Scanner-Verhalten ─────────────────────────────────────────────────────────
SCAN_DWELL_TIME = 0.15        # Sekunden pro Kanal beim Scan
SCAN_RESUME_DELAY = 3.5       # Sekunden auf aktivem Kanal vor Weiterscan
SQUELCH_DEFAULT    = -25  # dBFS, Startwert
SQUELCH_PRESETS    = [(-25, "Normal"), (-100, "Offen"), (-5, "Streng")]  # Menü-Presets (IQ-Leistung 10·log10, Bereich −30 bis −5 dBFS)
                          # Kalibrierung: ohne Signal messen → Schwelle ~3 dB über Rauschboden
SQUELCH_STEP       = 2    # dB pro Tastendruck
SQUELCH_HOLD_TIME  = 1.2  # Sekunden: Squelch bleibt nach Öffnen mindestens so lange offen.
                           # Verhindert Abschneiden bei kurzen Sprachpausen. War: 0.35
SQUELCH_HYSTERESIS = 5    # dB: Signal muss so weit unter die Schwelle fallen bevor Squelch
                           # schließt. Verhindert Flattern am Rand. War: 3

# ── Modi ──────────────────────────────────────────────────────────────────────
MODES = ["NFM", "FM", "WFM", "AM"]
MODE_BANDWIDTH = {
    "NFM": 12500,
    "FM":  16000,
    "WFM": 180000,
    "AM":  10000,
}

# Standard-Audio-LPF-Grenzfrequenz pro Betriebsart (Hz).
# Kein Eintrag = kein Filter (WFM: rtl_fm macht De-Emphasis selbst).
# Kann pro Kanal überschrieben werden (Channel.bandwidth).
MODE_AUDIO_LPF = {
    "NFM": 4000,
    "FM":  8000,
    "AM":  4000,
}

# ── Vorkonfigurierte Kanäle ───────────────────────────────────────────────────
# Format: {"name": str, "freq": Hz, "mode": str, "group": str}
CHANNELS = [
    {"name": "Leitstelle",      "freq": 155_325_000, "mode": "NFM", "group": "BOS"},
    {"name": "Feuerwehr 1",     "freq": 155_800_000, "mode": "NFM", "group": "BOS"},
    {"name": "Flughafen Twr",   "freq": 120_150_000, "mode": "AM",  "group": "Luft"},
    {"name": "Flughafen App",   "freq": 119_225_000, "mode": "AM",  "group": "Luft"},
    {"name": "WX Deutsch 1",    "freq": 162_400_000, "mode": "WFM", "group": "Info"},
    {"name": "Taxizentrale",    "freq": 466_975_000, "mode": "NFM", "group": "Misc"},
    {"name": "PMR Kanal 1",     "freq": 446_006_250, "mode": "NFM", "group": "PMR"},
    {"name": "PMR Kanal 8",     "freq": 446_093_750, "mode": "NFM", "group": "PMR"},
]

# ── GPIO-Pins (BCM-Nummerierung) ──────────────────────────────────────────────
# Alle Pins im unteren Header-Block (Pins 29–40), konfliktfrei mit Waveshare 3,5" SPI-Display.
# Das Display belegt GPIO 7–11, 17, 18, 25, 27 (Pins 11–26) → kein Überschneiden.
#
# Verdrahtung (Phys. Pin → Funktion):
#   Pin 29  GPIO 5  ENC_A       Pin 30  GND (Encoder)
#   Pin 31  GPIO 6  ENC_B       Pin 32  –
#   Pin 33  GPIO 13 ENC_SW      Pin 34  GND (Encoder)
#   Pin 35  GPIO 19 BTN_MODE    Pin 36  GPIO 16 BTN_SCAN
#   Pin 37  GPIO 26 BTN_SQ_DN   Pin 38  GPIO 20 BTN_MEMORY
#   Pin 39  GND (Tasten)        Pin 40  GPIO 21 BTN_SQ_UP
GPIO_BTN_SCAN   = 16   # Pin 36
GPIO_BTN_MODE   = 19   # Pin 35
GPIO_BTN_MEMORY = 20   # Pin 38
GPIO_BTN_SQ_UP  = 21   # Pin 40
GPIO_BTN_SQ_DN  = 26   # Pin 37
GPIO_ENC_A      = 5    # Pin 29
GPIO_ENC_B      = 6    # Pin 31
GPIO_ENC_SW     = 13   # Pin 33
GPIO_ENC_VCC    = 12   # Pin 32 – als Output-HIGH für Encoder-+ (3,3V)

# ── Display ───────────────────────────────────────────────────────────────────
DISPLAY_WIDTH  = 480
DISPLAY_HEIGHT = 320
DISPLAY_FPS    = 15           # Framerate – 15 reicht für ein Scanner-UI
DISPLAY_BRIGHTNESS = 80       # 0–100 Starthelligkeit
DISPLAY_BL_LEVELS  = [100, 70, 40, 15]  # Stufen zum Durchschalten per Menü

# ── Touchscreen ───────────────────────────────────────────────────────────────
# Waveshare 3,5" resistiver Touch meldet sich als /dev/input/touchscreen
# Kalibrierung einmalig mit: sudo ts_calibrate
TOUCH_ENABLED  = True
TOUCH_SWAP_XY  = False   # True wenn X/Y vertauscht (Hochformat → Querformat)
TOUCH_INVERT_X = False   # True bei gespiegelter X-Achse
TOUCH_INVERT_Y = False   # True bei gespiegelter Y-Achse

# Farben (R, G, B)
COLOR_BG        = (10,  12,  20)
COLOR_PRIMARY   = (0,  200, 160)   # Türkis – Hauptakzent
COLOR_DIM       = (40,  55,  70)
COLOR_TEXT      = (220, 230, 240)
COLOR_MUTED     = (90, 110, 130)
COLOR_ACTIVE    = (0,  220, 100)   # Grün – aktiver Empfang
COLOR_SCAN      = (255, 180,   0)  # Gelb – Scan läuft
COLOR_WARN      = (220,  60,  60)  # Rot – Fehler

# ── Bluetooth ─────────────────────────────────────────────────────────────────
BT_DEVICE_ADDRESS  = ""     # MAC nach erstem Pairing automatisch eingetragen
BT_AUTO_RECONNECT  = True   # beim Start versuchen zu verbinden

# ── Web-UI ────────────────────────────────────────────────────────────────────
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000

# ── Datenbank ─────────────────────────────────────────────────────────────────
DB_PATH = "bookmarks.db"
LOG_ACTIVITY = True           # Empfangsereignisse in DB mitloggen
