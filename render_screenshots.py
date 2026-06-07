#!/usr/bin/env python3
"""
Rendert alle UI-Zustände des SDR Scanners als PNG-Dateien.
Läuft ohne Hardware (offscreen pygame, kein SDL-Fenster).

Ausgabe: docs/screenshots/*.png (960×640 – 2× SPI-Auflösung)
"""

import os
import sys

os.environ['SDL_VIDEODRIVER'] = 'offscreen'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['SDL_NOMOUSE']     = '1'
sys.path.insert(0, os.path.dirname(__file__))

import pygame
pygame.display.init()
pygame.font.init()

import config.settings as cfg
from ui.display import DisplayUI, W, H, BG

OUT_DIR = os.path.join(os.path.dirname(__file__), "docs", "screenshots")
os.makedirs(OUT_DIR, exist_ok=True)

SCALE = 2   # 480×320 → 960×640


# ── Mock-Scanner ──────────────────────────────────────────────────────────────

def _bank_summary():
    return [
        {"bank": 0, "name": "BOS",       "count": 4, "active": True},
        {"bank": 1, "name": "PMR",       "count": 2, "active": False},
        {"bank": 2, "name": "FM Radio",  "count": 3, "active": False},
        {"bank": 3, "name": "HAM",       "count": 1, "active": False},
        {"bank": 4, "name": "Bank 5",    "count": 0, "active": False},
        {"bank": 5, "name": "Bank 6",    "count": 0, "active": False},
        {"bank": 6, "name": "Bank 7",    "count": 0, "active": False},
        {"bank": 7, "name": "Bank 8",    "count": 0, "active": False},
        {"bank": 8, "name": "Bank 9",    "count": 0, "active": False},
        {"bank": 9, "name": "Bank 10",   "count": 0, "active": False},
    ]

def _base_status(**overrides):
    s = {
        "state":       "IDLE",
        "scanning":    False,
        "channel":     "DB0FT",
        "freq":        145_600_000,
        "freq_mhz":    "145.6000",
        "mode":        "NFM",
        "group":       "HAM",
        "ch_index":    0,
        "ch_total":    8,
        "squelch_open": False,
        "rssi":        -72.0,
        "signal_bar":  0,
        "sq_level":    -25,
        "bandwidth":   None,
        "volume":      80,
        "bank":        0,
        "bank_name":   "BOS",
        "bank_summary": _bank_summary(),
        "audio_gain":  1.0,
        "calib_log":   [],
        "dongle_ok":   True,
        "comp_enabled": False,
        "agc_enabled":  False,
        "enc_vol_mode": False,
        "scan_all_banks": False,
        "loaded_bank":  0,
        "bt_connected": False,
        "bt_name":      "",
        "hotspot_on":         True,
        "hotspot_configured": True,
        "hotspot_busy":       False,
    }
    s.update(overrides)
    return s


class MockScanner:
    def __init__(self, overrides=None):
        self._overrides = overrides or {}

    def status_dict(self):
        return _base_status(**self._overrides)


# ── Render-Hilfsfunktion ──────────────────────────────────────────────────────

def render(ui: DisplayUI, pg, filename: str):
    canvas = pg.Surface((W, H))
    ui._draw(surface=canvas)
    scaled = pg.transform.smoothscale(canvas, (W * SCALE, H * SCALE))
    path = os.path.join(OUT_DIR, filename)
    pg.image.save(scaled, path)
    print(f"  ✓  {filename}")


def make_ui(scanner, state_overrides=None) -> DisplayUI:
    """Erstellt eine fertig initialisierte DisplayUI ohne Thread."""
    ui = DisplayUI(scanner, debug=True)
    ui._pg     = pygame
    ui._screen = pygame.display.set_mode((W, H))
    ui._load_fonts()
    ui._booting = False
    if state_overrides:
        for k, v in state_overrides.items():
            setattr(ui, k, v)
    return ui


# ── Szenen ────────────────────────────────────────────────────────────────────

pg = pygame

print(f"Rendere nach {OUT_DIR}/")

# 1. IDLE – kein Signal
ui = make_ui(MockScanner())
render(ui, pg, "idle_v2.png")

# 2. ACTIVE – Signal empfangen
ui = make_ui(MockScanner({
    "state":       "ACTIVE",
    "scanning":    True,
    "squelch_open": True,
    "rssi":        -38.0,
    "signal_bar":  4,
}))
render(ui, pg, "active_v2.png")

# 3. SCANNING – läuft durch
ui = make_ui(MockScanner({
    "state":       "SCANNING",
    "scanning":    True,
    "ch_index":    3,
    "channel":     "PMR Kanal 1",
    "freq_mhz":    "446.0063",
    "mode":        "NFM",
    "group":       "PMR",
}))
render(ui, pg, "scanning.png")

# 4. MENU – Overlay
ui = make_ui(MockScanner({"state": "MENU"}))
render(ui, pg, "menu.png")

# 5. BANK_SELECT – Overlay
ui = make_ui(MockScanner({"state": "BANK_SELECT"}))
render(ui, pg, "bank_select.png")

# 6. Boot-Splash
ui = make_ui(MockScanner())
ui._booting = True
ui._boot_t  = 1.2
render(ui, pg, "boot_splash.png")

# 7. ACTIVE mit BT-Audio
ui = make_ui(MockScanner({
    "state":       "ACTIVE",
    "scanning":    True,
    "squelch_open": True,
    "rssi":        -42.0,
    "signal_bar":  3,
    "bt_connected": True,
    "bt_name":     "JBL Flip 6",
}))
render(ui, pg, "active_bt_v2.png")

pg.quit()
print("Fertig.")
