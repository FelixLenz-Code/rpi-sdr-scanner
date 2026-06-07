# ui/display.py
# pygame-UI für 3,5" SPI-Display (480×320, Framebuffer /dev/fb1)
# Läuft ohne X11 direkt gegen den Linux-Framebuffer.
#
# Zustände:
#   IDLE        → Hauptansicht
#   SCANNING    → Hauptansicht + Scan-Fortschrittsbalken
#   ACTIVE      → Hauptansicht + grüner Empfangs-Rahmen
#   MENU        → Menü-Overlay über Hauptansicht
#   BANK_SELECT → Bank-Auswahl-Overlay

import threading
import logging
import os
import time

import config.settings as cfg

log = logging.getLogger(__name__)

# ── Farben ────────────────────────────────────────────────────────────────────
BG      = cfg.COLOR_BG
PRIMARY = cfg.COLOR_PRIMARY
DIM     = cfg.COLOR_DIM
TEXT    = cfg.COLOR_TEXT
MUTED   = cfg.COLOR_MUTED
ACTIVE  = cfg.COLOR_ACTIVE
SCAN_C  = cfg.COLOR_SCAN
WARN    = cfg.COLOR_WARN

# Overlay-Farben
OVERLAY_BG    = (18, 22, 35)      # etwas heller als BG für Tiefe
OVERLAY_SEL   = (0, 160, 120)    # ausgewählter Menüpunkt
OVERLAY_ITEM  = (35, 50, 68)     # inaktiver Menüpunkt
OVERLAY_BORD  = (0, 200, 160)    # Rahmenfarbe Overlay

W = cfg.DISPLAY_WIDTH   # 480
H = cfg.DISPLAY_HEIGHT  # 320


class DisplayUI:
    def __init__(self, scanner, debug: bool = False,
                 hdmi: bool = False, hdmi_size: tuple | None = None):
        self._scanner  = scanner
        self._debug    = debug
        self._hdmi     = hdmi
        self._hdmi_size = hdmi_size or (960, 640)   # Default: 2× SPI-Auflösung
        self._running  = False
        self._thread: threading.Thread | None = None
        self._pg       = None
        self._screen   = None
        self._fonts: dict = {}
        self._menu_idx = 0   # aktuell markierter Menüpunkt

        # Direct-Framebuffer-Modus (SDL2 hat kein fbcon/fbdev)
        self._fb_file  = None   # offenes /dev/fbX
        self._np       = None   # numpy-Referenz

        # Menü-Zustand

        # Touch-Menü-Zustand
        self._touch_menu_open:    bool = False
        self._touch_monitor_on:   bool = False  # Monitor-Modus aktiv via Touch

        # BT-Wizard-Zustand
        self._bt_phase    = "PAIRED"     # PAIRED|PAIRED_DETAIL|SCAN|SELECT|CONNECTING|DONE|ERROR|REMOVING
        self._bt_devices: list = []      # gefundene BTDevice-Objekte (Scan)
        self._bt_cursor   = 0
        self._bt_progress = 0.0          # 0.0–1.0 Scanfortschritt
        self._bt_message  = ""           # Fehlermeldung / Statustext
        self._bt_paired_devices: list = []   # bekannte/gekoppelte Geräte
        self._bt_paired_cursor  = 0
        self._bt_paired_selected = None      # Gerät in PAIRED_DETAIL
        self._bt_detail_cursor   = 0         # 0=Verbinden, 1=Entfernen

        # Skalierungsfaktor: Verhältnis HDMI-Auflösung zu SPI-Auflösung (480×320)
        # Im HDMI-Modus werden alle Koordinaten mit diesem Faktor multipliziert.
        if hdmi:
            self._sx = self._hdmi_size[0] / 480   # X-Skalierung
            self._sy = self._hdmi_size[1] / 320   # Y-Skalierung
            # Gleichmäßige Skalierung: nimm den kleineren Faktor, zentriere den Rest
            self._scale = min(self._sx, self._sy)
            self._ox = (self._hdmi_size[0] - int(480 * self._scale)) // 2  # X-Offset
            self._oy = (self._hdmi_size[1] - int(320 * self._scale)) // 2  # Y-Offset
        else:
            self._scale = 1.0
            self._sx = 1.0
            self._sy = 1.0
            self._ox = 0
            self._oy = 0

    # ── Starten / Stoppen ─────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="display"
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._fb_file:
            try:
                self._fb_file.close()
            except Exception:
                pass

    # ── Direct-Framebuffer-Hilfsmethoden ─────────────────────────────────────

    @staticmethod
    def _find_ili9486_fb() -> str | None:
        """Gibt den Pfad zum ILI9486-Framebuffer zurück (/dev/fb0, /dev/fb1 …)."""
        import glob
        for d in sorted(glob.glob('/sys/class/graphics/fb*')):
            try:
                name = open(f'{d}/name').read().strip().lower()
                if 'ili9486' in name or 'fb_ili' in name:
                    return f'/dev/{os.path.basename(d)}'
            except OSError:
                pass
        return None

    def _write_to_fb(self, surface) -> None:
        """Konvertiert pygame-Surface (RGB888) → RGB565 und schreibt in /dev/fbX."""
        np = self._np
        try:
            # surfarray.array3d liefert (W, H, 3) → transpose zu (H, W, 3)
            arr = self._pg.surfarray.array3d(surface).transpose(1, 0, 2)
            r = arr[:, :, 0].astype(np.uint16) >> 3   # 5 bit
            g = arr[:, :, 1].astype(np.uint16) >> 2   # 6 bit
            b = arr[:, :, 2].astype(np.uint16) >> 3   # 5 bit
            rgb565 = (r << 11) | (g << 5) | b
            self._fb_file.seek(0)
            self._fb_file.write(rgb565.tobytes())
        except Exception as e:
            log.error("FB-Write: %s", e)


    # ── Render-Loop ───────────────────────────────────────────────────────────

    def _run(self):
        try:
            import pygame
            self._pg = pygame
        except ImportError:
            log.warning("pygame nicht installiert – Display deaktiviert")
            return

        pg = self._pg

        if self._hdmi:
            # HDMI-Modus: normaler Desktop-SDL-Output
            os.environ.pop("SDL_VIDEODRIVER", None)
            os.environ.pop("SDL_FBDEV", None)
            os.environ.pop("SDL_NOMOUSE", None)
            log.info("HDMI-Modus: %dx%d (Skalierung %.2f×, Offset %d/%d)",
                     *self._hdmi_size, self._scale, self._ox, self._oy)
        elif not self._debug:
            # SDL2 unterstützt kein fbcon/fbdev → offscreen rendern, Pixel
            # dann per numpy in RGB565 konvertieren und direkt in /dev/fbX schreiben.
            fb_path = self._find_ili9486_fb()
            if fb_path:
                try:
                    import numpy as np
                    self._np = np
                    self._fb_file = open(fb_path, 'wb')  # noqa: SIM115
                    os.environ['SDL_VIDEODRIVER'] = 'offscreen'
                    os.environ.pop('SDL_FBDEV', None)
                    log.info("Direct-FB Modus: %s (numpy %s)", fb_path, np.__version__)
                except Exception as e:
                    log.error("Direct-FB Init fehlgeschlagen: %s – fallback", e)
            else:
                log.warning("Kein ILI9486-Framebuffer gefunden")

        pg.init()
        pg.mouse.set_visible(False)

        try:
            if self._hdmi:
                self._screen = pg.display.set_mode(self._hdmi_size, pg.RESIZABLE)
                pg.display.set_caption("SDR Scanner – HDMI Preview")
            else:
                # Im Direct-FB- und Debug-Modus kein FULLSCREEN (SDL kennt keinen Monitor)
                self._screen = pg.display.set_mode((W, H))
        except Exception as e:
            log.error("Display-Init fehlgeschlagen: %s", e)
            return

        pg.display.set_caption("SDR Scanner")
        self._load_fonts()
        self._start_evdev_touch(pg)
        clock = pg.time.Clock()

        while self._running:
            for ev in pg.event.get():
                if ev.type == pg.QUIT:
                    self._running = False
                elif ev.type == pg.KEYDOWN:
                    self._handle_key(ev.key)
                elif ev.type == pg.MOUSEBUTTONDOWN:
                    self._handle_touch(*ev.pos)
                elif ev.type == pg.USEREVENT:
                    pass  # reserviert
                elif ev.type == pg.FINGERDOWN:
                    self._handle_touch(int(ev.x * W), int(ev.y * H))
                elif ev.type == pg.VIDEORESIZE and self._hdmi:
                    # Fenstergröße angepasst → Skalierung neu berechnen
                    self._hdmi_size = (ev.w, ev.h)
                    self._scale = min(ev.w / 480, ev.h / 320)
                    self._ox = (ev.w - int(480 * self._scale)) // 2
                    self._oy = (ev.h - int(320 * self._scale)) // 2
                    self._screen = pg.display.set_mode(self._hdmi_size, pg.RESIZABLE)
                    self._load_fonts()   # Fonts für neue Größe neu laden

            if self._hdmi:
                # Intern auf 480×320 rendern, dann skaliert auf HDMI-Fenster blitten
                canvas = pg.Surface((W, H))
                self._draw(surface=canvas)
                sw = int(480 * self._scale)
                sh = int(320 * self._scale)
                scaled = pg.transform.smoothscale(canvas, (sw, sh))
                self._screen.fill(BG)
                self._screen.blit(scaled, (self._ox, self._oy))
                pg.display.flip()
            elif self._fb_file:
                self._draw()
                self._write_to_fb(self._screen)
            else:
                self._draw()
                pg.display.flip()
            clock.tick(cfg.DISPLAY_FPS)

        pg.quit()

    # ── Fonts ─────────────────────────────────────────────────────────────────

    def _load_fonts(self):
        pg = self._pg
        # Im HDMI-Modus rendern wir auf dem 480×320 Canvas – Fonts bleiben gleich.
        # smoothscale sorgt dann für scharfe Ausgabe auf dem Fenster.
        # Für noch schärfere Fonts bei großem Fenster: Canvas-Größe erhöhen.
        try:
            self._fonts["freq"]   = pg.font.SysFont("dejavusansmono", 44, bold=True)
            self._fonts["big"]    = pg.font.SysFont("dejavusans",     26, bold=True)
            self._fonts["med"]    = pg.font.SysFont("dejavusans",     18)
            self._fonts["small"]  = pg.font.SysFont("dejavusans",     14)
            self._fonts["tiny"]   = pg.font.SysFont("dejavusans",     11)
            self._fonts["menu"]   = pg.font.SysFont("dejavusans",     17, bold=True)
            self._fonts["menusub"]= pg.font.SysFont("dejavusans",     13)
        except Exception:
            f = pg.font.Font(None, 24)
            self._fonts = {k: f for k in
                ["freq","big","med","small","tiny","menu","menusub"]}

    # ═════════════════════════════════════════════════════════════════════════
    #  HAUPT-DRAW-DISPATCHER
    # ═════════════════════════════════════════════════════════════════════════

    def _draw(self, surface=None):
        if not self._fonts or self._screen is None:
            return
        s = self._scanner.status_dict()
        scr_orig = self._screen
        if surface is not None:
            self._screen = surface   # Temporär auf Canvas umleiten
        try:
            self._screen.fill(BG)
            self._draw_main(s)

            state = s["state"]
            # Touch-Menü schließen wenn ein anderer Overlay-Zustand eintritt
            if self._touch_menu_open and state not in ("IDLE", "SCANNING", "ACTIVE"):
                self._touch_menu_open = False

            if self._touch_menu_open:
                self._draw_touch_menu(s)
            elif state == "MENU":
                self._draw_menu_overlay(s)
            elif state == "BANK_SELECT":
                self._draw_bank_overlay(s)
            elif state == "CALIBRATING":
                self._draw_calib_overlay(s)
            elif state == "BT_SETUP":
                # Wizard starten wenn Phase noch nicht gesetzt (frischer Eintritt)
                if not hasattr(self, '_bt_wizard_active') or not self._bt_wizard_active:
                    self._bt_wizard_active = True
                    threading.Thread(target=self.bt_wizard_open,
                                     daemon=True, name="bt-wizard-init").start()
                self._draw_bt_overlay()

        finally:
            if surface is not None:
                self._screen = scr_orig   # Screen zurücksetzen

    # ═════════════════════════════════════════════════════════════════════════
    #  HAUPTANSICHT  (immer sichtbar, auch unter Overlays)
    # ═════════════════════════════════════════════════════════════════════════

    def _draw_main(self, s: dict):
        pg  = self._pg
        scr = self._screen

        # ── Statusleiste oben ─────────────────────────────────────────────
        state_color = {
            "IDLE":        DIM,
            "SCANNING":    SCAN_C,
            "ACTIVE":      ACTIVE,
            "MENU":        PRIMARY,
            "BANK_SELECT": (60, 40, 120),
            "CALIBRATING": (180, 100, 0),
        }.get(s["state"], DIM)

        pg.draw.rect(scr, state_color, (0, 0, W, 26))
        state_lbl = {
            "IDLE":        "BEREIT",
            "SCANNING":    "SCAN  ●",
            "ACTIVE":      "▶ EMPFANG",
            "MENU":        "▶ MENÜ",
            "BANK_SELECT": "▶ BANK WAHL",
            "CALIBRATING": "KALIBRIERUNG",
        }.get(s["state"], s["state"])
        self._text(state_lbl, "small", (8, 13), (8, 8, 8), anchor="ml")

        bank_str = f"B{s['bank']} {s['bank_name']}"
        self._text(bank_str, "small", (W // 2, 13), (8, 8, 8), anchor="mc")

        sq_str = f"SQ {s['sq_level']}  VOL {s['volume']}%"
        self._text(sq_str, "small", (W - 6, 13), (8, 8, 8), anchor="mr")

        # ── Frequenz ──────────────────────────────────────────────────────
        freq_txt = f"{s['freq_mhz']} MHz"
        self._text(freq_txt, "freq", (W // 2, 90), TEXT, anchor="mc")

        # ── Kanalname ─────────────────────────────────────────────────────
        name = s["channel"].split("(")[0].strip()
        # Name kürzen wenn zu lang
        if len(name) > 22:
            name = name[:21] + "…"
        self._text(name, "big", (W // 2, 140), PRIMARY, anchor="mc")

        # Mode + Kanalposition
        mode_str = f"{s['mode']}  ·  {s['ch_index'] + 1} / {s['ch_total']}"
        self._text(mode_str, "med", (W // 2, 168), MUTED, anchor="mc")

        # ── Signal-Balken ─────────────────────────────────────────────────
        self._draw_signal_bars(scr, 14, 198, s["signal_bar"], s["squelch_open"])
        rssi_str = f"{s['rssi']:.0f} dBFS"
        self._text(rssi_str, "small", (98, 210), MUTED, anchor="ml")

        # ── SDR-Dongle-Indikator ──────────────────────────────────────────
        if s.get("dongle_ok"):
            self._text("SDR ●", "small", (W - 6, 210), PRIMARY, anchor="mr")
        else:
            self._text("SDR ✕", "small", (W - 6, 210), WARN, anchor="mr")


        # ── Bluetooth-Status ──────────────────────────────────────────────
        BT_COL = (0, 160, 255)
        cx, cy = 18, 244
        if s.get("bt_connected"):
            # Gefüllter Kreis + Gerätenamen
            pg.draw.circle(scr, BT_COL, (cx, cy), 6)
            name = (s.get("bt_name") or "BT")[:14]
            self._text(name, "small", (cx + 11, cy), BT_COL, anchor="ml")
        elif cfg.BT_DEVICE_ADDRESS:
            # Leerer Kreis = bekanntes Gerät, nicht verbunden
            pg.draw.circle(scr, DIM, (cx, cy), 6, 1)
            self._text("BT", "small", (cx + 11, cy), DIM, anchor="ml")

        # ── Aktiv-Rahmen wenn Signal ──────────────────────────────────────
        if s["state"] == "ACTIVE":
            pg.draw.rect(scr, ACTIVE, (0, 0, W, H), 3)

        # ── Scan-Fortschrittsbalken ───────────────────────────────────────
        if s["state"] == "SCANNING":
            bw = int((s["ch_index"] / max(1, s["ch_total"])) * W)
            pg.draw.rect(scr, DIM,    (0,  H - 5, W,  5))
            pg.draw.rect(scr, SCAN_C, (0,  H - 5, bw, 5))

        # ── Encoder-Modus-Indikator ───────────────────────────────────────
        if s["state"] in ("IDLE", "ACTIVE") and s.get("enc_vol_mode"):
            self._text("◉ VOL", "small", (W - 10, 244), (255, 200, 0), anchor="mr")

        # ── Hinweiszeile unten ────────────────────────────────────────────
        if s["state"] not in ("MENU", "BANK_SELECT"):
            enc_vol = s.get("enc_vol_mode", False)
            if s["state"] == "ACTIVE":
                enc_hint = "Lautstärke" if enc_vol else "Überspringen"
                hint = f"[ENC] {enc_hint}  [MEM] Speichern  [ENC lang] Menü"
            elif s["state"] == "SCANNING":
                hint = "[SCAN] Stop  [ENC] Lautstärke  [ENC lang] Menü"
            else:
                enc_hint = "Lautstärke" if enc_vol else "Kanal"
                hint = f"[SCAN] Start  [ENC] {enc_hint}  [MODE] Modus  [ENC lang] Menü"
            self._text(hint, "tiny", (W // 2, H - 10), MUTED, anchor="mc")

    # ═════════════════════════════════════════════════════════════════════════
    #  TOUCH-MENÜ  (öffnet sich bei Klick auf Hauptansicht)
    # ═════════════════════════════════════════════════════════════════════════

    # Grid-Konstanten (werden auch im Touch-Handler genutzt)
    _TM_COLS    = 4
    _TM_ROWS    = 3
    _TM_GAP     = 6
    _TM_INFO_H  = 28                                              # Info-Leiste Höhe
    _TM_BTN_W   = (W - (_TM_COLS + 1) * _TM_GAP) // _TM_COLS    # 112 px
    _TM_BTN_H   = (H - 26 - _TM_INFO_H - (_TM_ROWS + 1) * _TM_GAP) // _TM_ROWS  # 74 px
    _TM_START_Y = 26 + _TM_INFO_H  # unterhalb Statusleiste + Info-Leiste

    # Button-Definitionen: (label, sublabel_fn, action, color_fn)
    # label/sublabel können Callables sein die s (status_dict) erhalten
    _TM_BUTTONS = [
        # Zeile 1
        ("◀ Kanal",  None,                 "KANAL_DOWN",   lambda s: DIM),
        ("Scan",     None,                 "SCAN_TOGGLE",  lambda s: (0, 180, 80) if s["scanning"] else PRIMARY),
        ("Kanal ▶",  None,                 "KANAL_UP",     lambda s: DIM),
        ("Modus",    lambda s: s["mode"],  "MODE",         lambda s: (80, 60, 130)),
        # Zeile 2
        ("Vol −",    lambda s: f"{s['volume']}%", "VOL_DOWN", lambda s: DIM),
        ("Menü",     None,                 "MENU",         lambda s: (40, 55, 80)),
        ("Vol +",    lambda s: f"{s['volume']}%", "VOL_UP",   lambda s: DIM),
        ("Monitor",  None,                 "MONITOR",      lambda s: ACTIVE),
        # Zeile 3
        ("SQ −",     lambda s: f"{s['sq_level']} dB", "SQ_DOWN", lambda s: DIM),
        ("BT",       lambda s: (s.get("bt_name") or "")[:10], "BT", lambda s: (0, 130, 220)),
        ("SQ +",     lambda s: f"{s['sq_level']} dB", "SQ_UP",   lambda s: DIM),
        ("X",        None,                 "CLOSE",        lambda s: (80, 20, 20)),
    ]

    def _draw_touch_menu(self, s: dict):
        pg  = self._pg
        scr = self._screen

        # Halbtransparentes Overlay über Hauptansicht
        overlay = pg.Surface((W, H - 26), pg.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        scr.blit(overlay, (0, 26))

        # ── Info-Leiste: aktuelle Frequenz, Kanal, Modus, Vol, SQ ───────────────
        info_y = 26 + self._TM_INFO_H // 2
        freq   = s.get("freq_mhz", "–")
        ch_name = s.get("channel", "–").split("(")[0].strip()[:18]
        mode   = s.get("mode", "–")
        vol    = s.get("volume", 0)
        sq     = s.get("sq_level", 0)
        pg.draw.rect(scr, (15, 22, 38), (0, 26, W, self._TM_INFO_H))
        pg.draw.line(scr, DIM, (0, 26 + self._TM_INFO_H - 1), (W, 26 + self._TM_INFO_H - 1), 1)
        self._text(f"{freq} MHz", "small", (6, info_y), PRIMARY, anchor="ml")
        self._text(ch_name,       "small", (W // 2, info_y), TEXT,  anchor="mc")
        self._text(f"{mode}  Vol {vol}%  SQ {sq}", "small", (W - 6, info_y), MUTED, anchor="mr")

        is_scanning = s.get("scanning", False)
        is_monitor  = self._touch_monitor_on

        for i, (lbl, sub_fn, action, col_fn) in enumerate(self._TM_BUTTONS):
            col = i % self._TM_COLS
            row = i // self._TM_COLS
            bx  = self._TM_GAP + col * (self._TM_BTN_W + self._TM_GAP)
            by  = self._TM_START_Y + row * (self._TM_BTN_H + self._TM_GAP)

            # Zustandsabhängige Farbe und Label-Anpassung
            active = False
            if action == "SCAN_TOGGLE":
                active = is_scanning
                lbl    = "■ Stop" if is_scanning else "▶ Scan"
            elif action == "MONITOR":
                active = is_monitor
                lbl    = "Monitor ●" if is_monitor else "Monitor"
            elif action == "BT":
                active = s.get("bt_connected", False)

            base_col = col_fn(s)
            bg  = base_col if active else (25, 38, 55)
            brd = base_col
            tc  = (8, 8, 8) if active else TEXT

            pg.draw.rect(scr, bg,  (bx, by, self._TM_BTN_W, self._TM_BTN_H), border_radius=8)
            pg.draw.rect(scr, brd, (bx, by, self._TM_BTN_W, self._TM_BTN_H), 1, border_radius=8)

            cx = bx + self._TM_BTN_W // 2
            sub = sub_fn(s) if sub_fn else None
            if sub:
                self._text(lbl, "menu",  (cx, by + self._TM_BTN_H // 2 - 11), tc, anchor="mc")
                self._text(sub, "small", (cx, by + self._TM_BTN_H // 2 + 9),
                           (8,8,8) if active else MUTED, anchor="mc")
            else:
                self._text(lbl, "menu",  (cx, by + self._TM_BTN_H // 2), tc, anchor="mc")

    def _touch_touch_menu(self, tx: int, ty: int):
        """Touch-Events innerhalb des Touch-Menüs."""
        for i in range(len(self._TM_BUTTONS)):
            col = i % self._TM_COLS
            row = i // self._TM_COLS
            bx  = self._TM_GAP + col * (self._TM_BTN_W + self._TM_GAP)
            by  = self._TM_START_Y + row * (self._TM_BTN_H + self._TM_GAP)
            if self._hit(tx, ty, bx, by, self._TM_BTN_W, self._TM_BTN_H):
                self._exec_touch_btn(self._TM_BUTTONS[i][2])
                return
        # Außerhalb getippt → schließen
        self._touch_menu_open = False
        self._draw()

    def _exec_touch_btn(self, action: str):
        """Führt eine Touch-Menü-Aktion aus."""
        from core.buttons import ButtonEvent
        sc = self._scanner

        if action == "CLOSE":
            self._touch_menu_open = False
        elif action == "MENU":
            self._touch_menu_open = False
            sc.buttons.inject(ButtonEvent.MENU)
        elif action == "BT":
            self._touch_menu_open = False
            sc.buttons.inject(ButtonEvent.BT_SETUP)
        elif action == "SCAN_TOGGLE":
            sc.buttons.inject(ButtonEvent.SCAN_TOGGLE)
        elif action == "KANAL_UP":
            sc.freq.next()
            sc._needs_retune = False      # debounce nicht abwarten
            sc._tune_current()            # sofort umschalten
        elif action == "KANAL_DOWN":
            sc.freq.prev()
            sc._needs_retune = False
            sc._tune_current()
        elif action == "VOL_UP":
            sc.audio.volume_up()
        elif action == "VOL_DOWN":
            sc.audio.volume_down()
        elif action == "SQ_UP":
            sc.squelch.increase()
            sc._save_squelch_to_channel()
        elif action == "SQ_DOWN":
            sc.squelch.decrease()
            sc._save_squelch_to_channel()
        elif action == "MODE":
            sc.freq.cycle_mode()          # direkt, kein Queue-Umweg
            sc._tune_current()
        elif action == "MONITOR":
            self._touch_monitor_on = not self._touch_monitor_on
            if self._touch_monitor_on:
                sc.buttons.inject(ButtonEvent.MONITOR_ON)
            else:
                sc.buttons.inject(ButtonEvent.MONITOR_OFF)

        sc.on_state_change()
        self._draw()

    # ═════════════════════════════════════════════════════════════════════════
    #  MENÜ-OVERLAY
    # ═════════════════════════════════════════════════════════════════════════

    def _get_menu_items(self) -> list[tuple[str, str]]:
        s = self._scanner.status_dict()
        scan_lbl = ("Scan: Alle Bänke [AN]" if s["scan_all_banks"]
                    else "Scan: Nur akt. Bank")
        sq = s["sq_level"]
        preset_names = {lvl: name for lvl, name in cfg.SQUELCH_PRESETS}
        sq_name = preset_names.get(sq, f"{sq} dBFS")
        sq_lbl = f"Squelch: {sq_name}"
        if s.get("bt_connected"):
            bt_lbl = f"BT: {s.get('bt_name','')[:14]}"
        else:
            bt_lbl = "Bluetooth-Setup"
        bank_lbl = f"Bank: B{s['bank']} {s['bank_name']}"
        if s.get("hotspot_busy"):
            hs_lbl = "Hotspot: Einrichten …"
        elif not s.get("hotspot_configured"):
            hs_lbl = "Hotspot einrichten"
        elif s.get("hotspot_on"):
            hs_lbl = "Hotspot: AN  ●"
        else:
            hs_lbl = "Hotspot: AUS ○"
        return [
            (bank_lbl,               "MEMORY"),
            ("Kalibrierung starten", "CALIBRATE"),
            (scan_lbl,               "__SCAN_ALL__"),
            (sq_lbl,                 "__SQ_PRESET__"),
            (bt_lbl,                 "BT_SETUP"),
            (hs_lbl,                 "__HOTSPOT__"),
            ("Menü schließen",       "__CLOSE__"),
        ]

    def _draw_menu_overlay(self, s: dict):
        pg  = self._pg
        scr = self._screen

        OX, OY = 30, 40          # Overlay-Ursprung
        OW, OH = W - 60, H - 70  # Overlay-Größe

        # Halbtransparenter Hintergrund (Surface mit Alpha)
        surf = pg.Surface((OW, OH), pg.SRCALPHA)
        surf.fill((*OVERLAY_BG, 235))
        scr.blit(surf, (OX, OY))

        # Rahmen
        pg.draw.rect(scr, OVERLAY_BORD, (OX, OY, OW, OH), 2, border_radius=8)

        # Titel
        self._text("MENÜ", "menu", (W // 2, OY + 18), PRIMARY, anchor="mc")
        pg.draw.line(scr, DIM, (OX + 10, OY + 30), (OX + OW - 10, OY + 30), 1)

        # Menüpunkte – item_h dynamisch damit alle Einträge in den Overlay passen
        items  = self._get_menu_items()
        avail  = OH - 38 - 28          # Platz nach Titel und vor Hint-Zeile
        item_h = min(34, avail // max(len(items), 1))
        for i, (label, _) in enumerate(items):
            iy = OY + 38 + i * item_h
            ir = (OX + 8, iy, OW - 16, item_h - 4)

            if i == self._menu_idx:
                pg.draw.rect(scr, OVERLAY_SEL, ir, border_radius=5)
                col = (8, 8, 8)
            else:
                pg.draw.rect(scr, OVERLAY_ITEM, ir, border_radius=5)
                col = TEXT

            # Auswahlpfeil
            if i == self._menu_idx:
                self._text("▶", "menusub",
                           (OX + 16, iy + item_h // 2 - 2), col, anchor="ml")

            self._text(label, "menu",
                       (OX + 30, iy + item_h // 2 - 2), col, anchor="ml")

        # Hinweis unten
        pg.draw.line(scr, DIM,
                     (OX + 10, OY + OH - 22),
                     (OX + OW - 10, OY + OH - 22), 1)
        self._text("[ENC] Navigieren  [ENC Druck] Auswählen  [ENC lang] Schließen",
                   "tiny", (W // 2, OY + OH - 10), MUTED, anchor="mc")

    def _menu_up(self):
        self._menu_idx = (self._menu_idx - 1) % len(self._get_menu_items())

    def _menu_down(self):
        self._menu_idx = (self._menu_idx + 1) % len(self._get_menu_items())

    # Öffentliche Schnittstelle für scanner.py
    def menu_cursor_up(self):   self._menu_up();   self._draw()
    def menu_cursor_down(self): self._menu_down(); self._draw()
    def menu_confirm(self):     self._menu_select()

    def _menu_select(self):
        from core.buttons import ButtonEvent
        _, action = self._get_menu_items()[self._menu_idx]

        if action == "__CLOSE__":
            self._scanner.buttons.inject(ButtonEvent.MENU)
            return

        # Toggle/Cycle-Aktionen: Menü bleibt offen, Label aktualisiert sich sofort
        if action == "__SCAN_ALL__":
            self._scanner.scan_all_banks = not self._scanner.scan_all_banks
            self._draw()
            return

        if action == "__SQ_PRESET__":
            presets = [lvl for lvl, _ in cfg.SQUELCH_PRESETS]
            cur = self._scanner.squelch.level
            try:
                idx = presets.index(cur)
            except ValueError:
                idx = -1
            self._scanner.squelch.level = presets[(idx + 1) % len(presets)]
            self._draw()
            return

        if action == "__HOTSPOT__":
            self._scanner.toggle_hotspot()
            self._draw()
            return

        # ButtonEvent-Aktionen: Menü zuerst schließen, dann Event ins IDLE injizieren
        self._scanner.buttons.inject(ButtonEvent.MENU)
        self._scanner.buttons.inject(ButtonEvent[action])

    # ═════════════════════════════════════════════════════════════════════════
    #  BANK-SELECT-OVERLAY
    # ═════════════════════════════════════════════════════════════════════════

    def _draw_bank_overlay(self, s: dict):
        pg  = self._pg
        scr = self._screen

        OX, OY = 20, 34
        OW, OH = W - 40, H - 60

        surf = pg.Surface((OW, OH), pg.SRCALPHA)
        surf.fill((*OVERLAY_BG, 240))
        scr.blit(surf, (OX, OY))
        pg.draw.rect(scr, (100, 60, 200), (OX, OY, OW, OH), 2, border_radius=8)

        self._text("BANK WÄHLEN", "menu", (W // 2, OY + 16), (180, 140, 255), anchor="mc")
        pg.draw.line(scr, DIM, (OX + 10, OY + 28), (OX + OW - 10, OY + 28), 1)

        # 2×5 Raster für 10 Bänke
        summary = s.get("bank_summary", [])
        cell_w = (OW - 20) // 5
        cell_h = 44

        for i, b in enumerate(summary):
            col_i = i % 5
            row_i = i // 5
            bx = OX + 10 + col_i * cell_w
            by = OY + 36 + row_i * (cell_h + 6)

            active   = b["active"]
            has_chs  = b["count"] > 0
            bg_col   = OVERLAY_SEL  if active else (OVERLAY_ITEM if has_chs else (20, 28, 40))
            txt_col  = (8, 8, 8)    if active else (TEXT if has_chs else MUTED)
            bord_col = (180, 140, 255) if active else DIM

            pg.draw.rect(scr, bg_col, (bx, by, cell_w - 4, cell_h), border_radius=5)
            pg.draw.rect(scr, bord_col, (bx, by, cell_w - 4, cell_h), 1 if not active else 2, border_radius=5)

            # Bank-Nummer
            self._text(str(i), "menu",
                       (bx + (cell_w - 4) // 2, by + 13), txt_col, anchor="mc")

            # Kanalanzahl
            count_str = f"{b['count']} Kan." if b["count"] else "leer"
            self._text(count_str, "tiny",
                       (bx + (cell_w - 4) // 2, by + 29), txt_col, anchor="mc")

            # Bank-Name (gekürzt)
            bname = b["name"]
            if bname.startswith("Bank "):
                bname = bname[5:]   # "Bank 0" → "0" schon oben, Name-Rest
            if len(bname) > 6:
                bname = bname[:5] + "…"
            # Nur anzeigen wenn kein Standard-Name
            if not b["name"].startswith(f"Bank {i}"):
                self._text(bname, "tiny",
                           (bx + (cell_w - 4) // 2, by + 38), txt_col, anchor="mc")

        # Aktive Bank + Hinweise
        active_b = s.get("bank", 0)
        active_name = s.get("bank_name", "")
        pg.draw.line(scr, DIM,
                     (OX + 10, OY + OH - 30),
                     (OX + OW - 10, OY + OH - 30), 1)
        self._text(f"Aktiv: B{active_b} – {active_name}", "menusub",
                   (W // 2, OY + OH - 20), PRIMARY, anchor="mc")
        self._text("[ENC] Wählen  [ENC Druck] Laden  [ENC lang] Abbruch",
                   "tiny", (W // 2, OY + OH - 8), MUTED, anchor="mc")

    # ═════════════════════════════════════════════════════════════════════════
    #  KALIBRIERUNGS-OVERLAY
    # ═════════════════════════════════════════════════════════════════════════

    def _draw_calib_overlay(self, s: dict):
        pg  = self._pg
        scr = self._screen

        OX, OY = 20, 34
        OW, OH = W - 40, H - 60

        surf = pg.Surface((OW, OH), pg.SRCALPHA)
        surf.fill((*OVERLAY_BG, 240))
        scr.blit(surf, (OX, OY))
        pg.draw.rect(scr, (180, 100, 0), (OX, OY, OW, OH), 2, border_radius=8)

        self._text("PPM-KALIBRIERUNG", "menu", (W // 2, OY + 16), (255, 180, 60), anchor="mc")
        pg.draw.line(scr, DIM, (OX + 10, OY + 28), (OX + OW - 10, OY + 28), 1)

        lines = s.get("calib_log", [])
        y0 = OY + 38
        for line in lines[-6:]:
            self._text(line, "small", (OX + 10, y0), cfg.COLOR_TEXT, anchor="tl")
            y0 += 16

    # ═════════════════════════════════════════════════════════════════════════
    #  BLUETOOTH-WIZARD
    # ═════════════════════════════════════════════════════════════════════════

    # ── BT-Overlay-Konstanten (auch für Touch-Hitbox) ─────────────────────────
    _BT_OX, _BT_OY = 15, 28
    _BT_OW, _BT_OH = W - 30, H - 50
    # Zurück-Button: unten links im Overlay
    _BT_BACK_X  = _BT_OX + 6            # 21
    _BT_BACK_Y  = _BT_OY + _BT_OH - 30  # 268 – vollbreit, gut antippbar
    _BT_BACK_W  = _BT_OW - 12           # 438 (volle Overlay-Breite)
    _BT_BACK_H  = 26

    def _draw_bt_back_btn(self, label: str = "← Zurück", selected: bool = False):
        """Zeichnet den Zurück/Schließen-Button unten links."""
        pg  = self._pg
        scr = self._screen
        bx, by = self._BT_BACK_X, self._BT_BACK_Y
        bg  = OVERLAY_SEL if selected else (30, 45, 65)
        tc  = (8, 8, 8)  if selected else MUTED
        pg.draw.rect(scr, bg,  (bx, by, self._BT_BACK_W, self._BT_BACK_H), border_radius=4)
        pg.draw.rect(scr, DIM, (bx, by, self._BT_BACK_W, self._BT_BACK_H), 1, border_radius=4)
        self._text(label, "menu", (bx + self._BT_BACK_W // 2, by + self._BT_BACK_H // 2),
                   tc, anchor="mc")

    def _bt_back_selected(self) -> bool:
        """Ist der Back-Button gerade mit dem Encoder ausgewählt?"""
        phase = self._bt_phase
        if phase == "PAIRED":
            return self._bt_paired_cursor == len(self._bt_paired_devices) + 1
        if phase == "PAIRED_DETAIL":
            return self._bt_detail_cursor == 2
        if phase == "SELECT":
            return self._bt_cursor == len(self._bt_devices) + 1
        return False

    def _draw_bt_overlay(self):
        pg  = self._pg
        scr = self._screen
        OX, OY = self._BT_OX, self._BT_OY
        OW, OH = self._BT_OW, self._BT_OH
        BT_COL = (0, 130, 220)

        surf = pg.Surface((OW, OH), pg.SRCALPHA)
        surf.fill((*OVERLAY_BG, 245))
        scr.blit(surf, (OX, OY))
        pg.draw.rect(scr, BT_COL, (OX, OY, OW, OH), 2, border_radius=8)
        self._text("BLUETOOTH", "menu", (W // 2, OY + 16), BT_COL, anchor="mc")
        pg.draw.line(scr, DIM, (OX + 10, OY + 28), (OX + OW - 10, OY + 28), 1)

        phase = self._bt_phase

        if phase == "PAIRED":
            paired   = self._bt_paired_devices
            add_idx  = len(paired)
            item_h   = 30
            max_vis  = 4
            start    = max(0, min(self._bt_paired_cursor - 1, add_idx - max_vis))

            for slot in range(max_vis):
                di = start + slot
                if di >= add_idx:
                    break
                dev      = paired[di]
                iy       = OY + 34 + slot * item_h
                selected = (di == self._bt_paired_cursor)
                pg.draw.rect(scr, OVERLAY_SEL if selected else OVERLAY_ITEM,
                             (OX + 6, iy, OW - 12, item_h - 3), border_radius=4)
                label = dev.display_name(19) if dev.has_name else dev.address[-11:]
                col_t = (8, 8, 8) if selected else (TEXT if dev.has_name else MUTED)
                self._text(label, "menu" if dev.has_name else "small",
                           (OX + 14, iy + 11), col_t, anchor="ml")
                if dev.connected:
                    self._text("●", "small", (OX + OW - 12, iy + 11), ACTIVE, anchor="mr")

            add_y   = OY + 34 + max_vis * item_h + 4
            add_sel = (self._bt_paired_cursor == add_idx)
            add_bg  = (0, 100, 180) if add_sel else (25, 40, 60)
            add_col = (255, 255, 255) if add_sel else (100, 150, 200)
            pg.draw.rect(scr, add_bg, (OX + 6, add_y, OW - 12, item_h - 3), border_radius=4)
            self._text("+ Neues Gerät suchen", "menu",
                       (W // 2, add_y + 11), add_col, anchor="mc")

            if not paired:
                self._text("Keine gekoppelten Geräte", "tiny",
                           (W // 2, OY + OH - 10), MUTED, anchor="mc")
            self._draw_bt_back_btn("Schliessen", self._bt_back_selected())

        elif phase == "PAIRED_DETAIL":
            dev = self._bt_paired_selected
            is_active = (dev is not None and
                         self._scanner.bt.connected_address == dev.address)
            if dev:
                status_col = ACTIVE if is_active else MUTED
                status_lbl = "● Verbunden" if is_active else "○ Nicht verbunden"
                self._text(dev.display_name(22), "big",
                           (W // 2, OY + 46), BT_COL, anchor="mc")
                self._text(status_lbl, "small",
                           (W // 2, OY + 72), status_col, anchor="mc")
            connect_lbl = "Trennen" if is_active else "Verbinden"
            connect_col = (220, 120, 0) if is_active else BT_COL
            connect_bg_dim = (80, 45, 0) if is_active else (0, 80, 160)
            options = [(connect_lbl,         connect_col,    connect_bg_dim),
                       ("Entfernen (Unpair)", (220, 60, 60),  (80, 20, 20))]
            for i, (lbl, col_t, col_bg_dim) in enumerate(options):
                iy       = OY + 96 + i * 44
                selected = (self._bt_detail_cursor == i)
                if i == 0:
                    bg = connect_col if selected else col_bg_dim
                else:
                    bg = (220, 60, 60) if selected else col_bg_dim
                tc = (255, 255, 255) if selected else col_t
                pg.draw.rect(scr, bg, (OX + 20, iy, OW - 40, 32), border_radius=6)
                self._text(lbl, "menu", (W // 2, iy + 16), tc, anchor="mc")
            self._draw_bt_back_btn("← Zurück", self._bt_back_selected())

        elif phase == "REMOVING":
            self._text("Entferne...", "med", (W // 2, OY + 60), WARN, anchor="mc")
            self._text(self._bt_message[:24], "big",
                       (W // 2, OY + 90), TEXT, anchor="mc")

        elif phase == "SCAN":
            spinner = r"-\|/"[int(time.time() * 4) % 4]
            pct = int(min(100, self._bt_progress * 100))
            phase_lbl = "Namen aufloesen..." if pct >= 99 else f"Suche Geraete... {pct}%"
            self._text(f"{spinner}  {phase_lbl}", "med",
                       (W // 2, OY + 55), BT_COL, anchor="mc")
            # Fortschrittsbalken
            bw = int((OW - 20) * self._bt_progress)
            pg.draw.rect(scr, DIM,    (OX + 10, OY + 72, OW - 20, 12), border_radius=3)
            pg.draw.rect(scr, BT_COL, (OX + 10, OY + 72, max(4, bw), 12), border_radius=3)
            # Gefundene Geräte bisher
            n = len(self._bt_devices)
            if n:
                self._text(f"{n} Geraet(e) gefunden", "small",
                           (W // 2, OY + 100), MUTED, anchor="mc")
            self._draw_bt_back_btn("Abbrechen")

        elif phase == "SELECT":
            devices   = self._bt_devices
            # Virtueller Index len(devices) = "Neu suchen"
            rescan_idx = len(devices)
            item_h  = 30
            max_vis = 4
            start   = max(0, min(self._bt_cursor - 1, rescan_idx - max_vis))

            # Gerät-Einträge
            for slot in range(max_vis):
                di = start + slot
                if di >= rescan_idx:
                    break
                dev      = devices[di]
                iy       = OY + 34 + slot * item_h
                selected = (di == self._bt_cursor)
                pg.draw.rect(scr, OVERLAY_SEL if selected else OVERLAY_ITEM,
                             (OX + 6, iy, OW - 12, item_h - 3), border_radius=4)
                has_name = dev.name != dev.address
                col_t  = (8, 8, 8) if selected else (TEXT if has_name else MUTED)
                label  = dev.display_name(19) if has_name else dev.address[-11:]
                self._text(label, "menu" if has_name else "small",
                           (OX + 14, iy + 11), col_t, anchor="ml")
                rssi_s = f"{dev.rssi}dB" if dev.rssi else "?"
                self._text(rssi_s, "tiny",
                           (OX + OW - 12, iy + 11), col_t, anchor="mr")

            # "Neu suchen"-Button (immer sichtbar)
            rescan_y  = OY + 34 + max_vis * item_h + 4
            rs_sel    = (self._bt_cursor == rescan_idx)
            rs_col_bg = (0, 100, 180) if rs_sel else (25, 40, 60)
            rs_col_t  = (255, 255, 255) if rs_sel else (100, 150, 200)
            pg.draw.rect(scr, rs_col_bg,
                         (OX + 6, rescan_y, OW - 12, item_h - 3), border_radius=4)
            self._text("+ Neu suchen", "menu",
                       (W // 2, rescan_y + 11), rs_col_t, anchor="mc")

            self._draw_bt_back_btn("← Zurück", self._bt_back_selected())

        elif phase == "CONNECTING":
            self._text("Verbinde (A2DP)...", "med",
                       (W // 2, OY + 65), TEXT, anchor="mc")
            if self._bt_devices and self._bt_cursor < len(self._bt_devices):
                dev = self._bt_devices[self._bt_cursor]
                self._text(dev.display_name(24), "big",
                           (W // 2, OY + 95), BT_COL, anchor="mc")

        elif phase == "DONE":
            self._text("Verbunden!", "big", (W // 2, OY + 55), ACTIVE, anchor="mc")
            name = self._bt_message or ""
            self._text(name[:26], "med", (W // 2, OY + 85), TEXT, anchor="mc")
            self._text("Audio -> Bluetooth", "small",
                       (W // 2, OY + 108), MUTED, anchor="mc")
            self._draw_bt_back_btn("Fertig")

        elif phase == "ERROR":
            self._text("Fehler!", "big", (W // 2, OY + 55), WARN, anchor="mc")
            self._text(self._bt_message[:28], "small",
                       (W // 2, OY + 85), MUTED, anchor="mc")
            self._draw_bt_back_btn("← Erneut suchen")

    # ── Wizard-Navigation (öffentlich, von scanner.py aufgerufen) ─────────────

    def bt_cursor_up(self):
        if self._bt_phase == "SELECT":
            self._bt_cursor = max(0, self._bt_cursor - 1)
            self._draw()
        elif self._bt_phase == "PAIRED":
            self._bt_paired_cursor = max(0, self._bt_paired_cursor - 1)
            self._draw()
        elif self._bt_phase == "PAIRED_DETAIL":
            self._bt_detail_cursor = max(0, self._bt_detail_cursor - 1)
            self._draw()

    def bt_cursor_down(self):
        # +1 über das letzte Listenelement hinaus = Back-Button
        if self._bt_phase == "SELECT":
            self._bt_cursor = min(len(self._bt_devices) + 1, self._bt_cursor + 1)
            self._draw()
        elif self._bt_phase == "PAIRED":
            self._bt_paired_cursor = min(len(self._bt_paired_devices) + 1,
                                         self._bt_paired_cursor + 1)
            self._draw()
        elif self._bt_phase == "PAIRED_DETAIL":
            self._bt_detail_cursor = min(2, self._bt_detail_cursor + 1)
            self._draw()

    def bt_back(self):
        """MENU-Taste im BT-Wizard: eine Ebene zurück oder Wizard schließen."""
        if self._bt_phase == "PAIRED_DETAIL":
            self._bt_phase = "PAIRED"
            self._draw()
        elif self._bt_phase == "SELECT":
            self._bt_phase = "PAIRED"
            self._draw()
        else:
            self._bt_wizard_close()

    def bt_confirm(self):
        phase = self._bt_phase
        if phase == "DONE":
            self._bt_wizard_close()
        elif phase in ("SCAN", "ERROR"):
            # Einzige Aktion: Neu suchen / Abbrechen
            self._bt_wizard_active = False
            self._bt_start_scan()
        elif phase == "PAIRED":
            n = len(self._bt_paired_devices)
            if self._bt_paired_cursor == n + 1:  # Back-Button
                self._bt_wizard_close()
            elif self._bt_paired_cursor == n:     # "+ Neues Gerät"
                self._bt_start_scan()
            elif self._bt_paired_devices:
                self._bt_paired_selected = self._bt_paired_devices[self._bt_paired_cursor]
                self._bt_detail_cursor   = 0
                self._bt_phase           = "PAIRED_DETAIL"
                self._draw()
        elif phase == "PAIRED_DETAIL":
            dev = self._bt_paired_selected
            if not dev:
                return
            if self._bt_detail_cursor == 2:  # Back-Button
                self.bt_back()
                return
            if self._bt_detail_cursor == 0:
                is_active = (self._scanner.bt.connected_address == dev.address)
                if is_active:
                    threading.Thread(target=self._scanner.bt.disconnect,
                                     daemon=True, name="bt-disconnect").start()
                    self._bt_wizard_close()
                else:
                    self._bt_start_connect(dev)
            else:
                self._bt_start_unpair(dev)
        elif phase == "SELECT":
            n = len(self._bt_devices)
            if self._bt_cursor == n + 1:     # Back-Button
                self.bt_back()
            elif self._bt_cursor == n:       # "Neu suchen"
                self._bt_wizard_active = False
                self._bt_start_scan()
            elif self._bt_devices:
                self._bt_start_connect(self._bt_devices[self._bt_cursor])

    def bt_wizard_open(self):
        """Startet den Wizard – zeigt zuerst bekannte Geräte, dann Scan."""
        self._bt_phase           = "PAIRED"
        self._bt_devices         = []
        self._bt_cursor          = 0
        self._bt_progress        = 0.0
        self._bt_message         = ""
        self._bt_paired_cursor   = 0
        self._bt_paired_selected = None
        self._bt_detail_cursor   = 0
        self._bt_paired_devices  = self._scanner.bt.get_paired_devices()
        self._draw()

    def _bt_wizard_close(self):
        self._bt_wizard_active = False
        from core.scanner import ScannerState
        self._scanner.state = ScannerState.IDLE
        self._scanner.on_state_change()

    def _bt_start_scan(self):
        self._bt_phase    = "SCAN"
        self._bt_progress = 0.0
        self._draw()
        threading.Thread(target=self._bt_scan_thread,
                         daemon=True, name="bt-scan").start()

    def _bt_scan_thread(self):
        bt = self._scanner.bt
        if not bt.available():
            self._bt_phase   = "ERROR"
            self._bt_message = "Kein BT-Adapter"
            return

        def _prog(elapsed, total):
            self._bt_progress = min(1.0, elapsed / total)
            # Zwischenergebnisse live anzeigen
            self._bt_devices = bt.last_scan_results()

        devices = bt.scan(duration=10.0, progress_cb=_prog)
        self._bt_devices = devices
        self._bt_phase   = "SELECT"
        self._bt_cursor  = 0

    def _bt_start_connect(self, dev):
        self._bt_phase = "PAIRING"
        self._draw()
        threading.Thread(
            target=self._bt_connect_thread, args=(dev,),
            daemon=True, name="bt-connect"
        ).start()

    def _bt_connect_thread(self, dev):
        bt = self._scanner.bt
        self._bt_phase = "CONNECTING"
        self._draw()
        ok = bt.connect(dev.address)
        if ok:
            bt.trust(dev.address)
            self._save_bt_address(dev.address)
            bt.connected_address = dev.address
            self._bt_phase   = "DONE"
            self._bt_message = dev.name
            self._draw()
            # A2DP-Sink setzen und Audio neu starten (im Hintergrund, Sink braucht Zeit)
            threading.Thread(
                target=self._apply_bt_audio, args=(dev.address,),
                daemon=True, name="bt-audio-setup"
            ).start()
        else:
            self._bt_phase   = "ERROR"
            self._bt_message = "Verbinden fehlgeschlagen"
            self._draw()
        self._scanner.on_state_change()

    def _bt_start_unpair(self, dev):
        self._bt_phase   = "REMOVING"
        self._bt_message = dev.name
        self._draw()
        threading.Thread(
            target=self._bt_unpair_thread, args=(dev,),
            daemon=True, name="bt-unpair"
        ).start()

    def _bt_unpair_thread(self, dev):
        bt = self._scanner.bt
        bt.remove_device(dev.address)
        # Falls es das gespeicherte Auto-Connect-Gerät war, Adresse löschen
        import config.settings as _cfg
        if dev.address == _cfg.BT_DEVICE_ADDRESS:
            self._save_bt_address("")
        # Zurück zur gepairten Liste (aktualisiert)
        self._bt_paired_devices = bt.get_paired_devices()
        self._bt_paired_cursor  = 0
        self._bt_phase          = "PAIRED"
        self._draw()
        self._scanner.on_state_change()

    def _apply_bt_audio(self, address: str) -> None:
        """Wartet auf A2DP-Sink, setzt ihn und startet Audio neu."""
        ok = self._scanner.bt.set_audio_sink(address)
        if ok:
            self._restart_audio()
            log.info("BT-Audio aktiv: %s", address)
        else:
            log.warning("BT-Audio: Sink nicht gefunden, Audio bleibt auf lokalem Gerät")

    def _restart_audio(self):
        """Startet die Audio-Pipeline neu — nötig nach Sink-Wechsel."""
        try:
            self._scanner.audio.stop()
            time.sleep(0.3)
            self._scanner.audio.start()
            log.info("Audio-Pipeline nach BT-Connect neu gestartet")
        except Exception as e:
            log.warning("Audio-Restart: %s", e)

    @staticmethod
    def _save_bt_address(address: str):
        """Schreibt BT_DEVICE_ADDRESS in config/settings.py UND aktualisiert das Modul im RAM."""
        import re, shutil
        import config.settings as _cfg_module
        # In-Memory sofort aktualisieren – sonst sieht der laufende Prozess den alten Wert
        _cfg_module.BT_DEVICE_ADDRESS = address
        try:
            path = __file__.replace('ui/display.py', 'config/settings.py')
            shutil.copy(path, path + '.bak')
            text = open(path).read()
            text = re.sub(
                r'BT_DEVICE_ADDRESS\s*=\s*"[^"]*"',
                f'BT_DEVICE_ADDRESS  = "{address}"',
                text
            )
            open(path, 'w').write(text)
        except Exception as e:
            log.warning("BT-Adresse speichern: %s", e)

    # ═════════════════════════════════════════════════════════════════════════
    #  HILFSMETHODEN
    # ═════════════════════════════════════════════════════════════════════════

    def _draw_signal_bars(self, scr, x: int, y: int, bars: int, open_sq: bool):
        pg    = self._pg
        color = ACTIVE if open_sq else PRIMARY
        for i in range(5):
            h    = 6 + i * 4
            rect = (x + i * 14, y + (20 - h), 10, h)
            pg.draw.rect(scr, color if i < bars else DIM, rect)

    def _text(self, text: str, font_key: str, pos: tuple,
              color=None, anchor: str = "ml"):
        if color is None:
            color = TEXT
        pg   = self._pg
        font = self._fonts.get(font_key, self._fonts["med"])
        surf = font.render(str(text), True, color)
        r    = surf.get_rect()
        x, y = pos
        if   anchor == "mc": r.center   = (x, y)
        elif anchor == "mr": r.midright = (x, y)
        else:                r.midleft  = (x, y)
        self._screen.blit(surf, r)

    # ═════════════════════════════════════════════════════════════════════════
    #  TASTATUR (Debug / angeschlossene USB-Tastatur)
    # ═════════════════════════════════════════════════════════════════════════

    # ── Touch-Eingabe (Menü + Bank-Select) ───────────────────────────────────

    @staticmethod
    def _hit(tx: int, ty: int, rx: int, ry: int, rw: int, rh: int) -> bool:
        return rx <= tx <= rx + rw and ry <= ty <= ry + rh

    # ── Evdev Touch-Reader ────────────────────────────────────────────────────

    def _start_evdev_touch(self, pg):
        """
        Startet einen Daemon-Thread der direkt vom ADS7846-Evdev-Device liest
        und pygame MOUSEBUTTONDOWN Events injiziert.
        SDL2 im offscreen-Modus liest keine Input-Geräte selbst.
        """
        import glob
        dev_path = None
        for path in sorted(glob.glob('/dev/input/event*')):
            try:
                name = open(f'/sys/class/input/{os.path.basename(path)}/device/name').read().strip()
                if 'ads7846' in name.lower() or 'touchscreen' in name.lower():
                    dev_path = path
                    break
            except Exception:
                continue
        if not dev_path:
            log.info("Kein Touch-Device gefunden – Touch deaktiviert")
            return
        log.info("Touch-Reader: %s", dev_path)
        threading.Thread(
            target=self._evdev_loop, args=(dev_path, pg),
            daemon=True, name="touch-evdev"
        ).start()

    def _evdev_loop(self, dev_path: str, pg):
        """Liest ADS7846-Rohevents und injiziert sie als pygame MOUSEBUTTONDOWN."""
        import struct, sys
        # struct input_event: (sec, usec, type, code, value)
        # 64-bit kernel: q q H H i = 24 bytes; 32-bit: l l H H i = 16 bytes
        FMT = 'qqHHi' if sys.maxsize > 2**32 else 'llHHi'
        SZ  = struct.calcsize(FMT)

        x_raw = y_raw = 0
        touching = just_pressed = False

        try:
            with open(dev_path, 'rb') as f:
                while self._running:
                    data = f.read(SZ)
                    if len(data) < SZ:
                        break
                    _, _, evtype, code, value = struct.unpack(FMT, data)

                    if evtype == 3:          # EV_ABS
                        if code == 0:
                            x_raw = value   # ABS_X  0–4095
                        elif code == 1:
                            y_raw = value   # ABS_Y  0–4095
                    elif evtype == 1 and code == 330:  # EV_KEY BTN_TOUCH
                        if value == 1:
                            touching = True
                            just_pressed = True
                        else:
                            touching = False
                    elif evtype == 0 and code == 0:    # EV_SYN SYN_REPORT
                        if just_pressed and touching:
                            just_pressed = False
                            # Rohdaten → Bildschirmkoordinaten
                            px = max(0, min(W - 1, x_raw * W // 4096))
                            py = max(0, min(H - 1, y_raw * H // 4096))
                            try:
                                pg.event.post(pg.event.Event(
                                    pg.MOUSEBUTTONDOWN,
                                    {'pos': (px, py), 'button': 1, 'touch': True}
                                ))
                            except Exception:
                                pass
        except Exception as e:
            log.warning("Touch-evdev: %s", e)

    def _handle_touch(self, tx: int, ty: int):
        if self._hdmi:
            # Im HDMI-Modus: Canvas-Offset und Skalierung rückrechnen
            tx = max(0, min(W - 1, int((tx - self._ox) / self._scale)))
            ty = max(0, min(H - 1, int((ty - self._oy) / self._scale)))
        else:
            # Achsen-Korrektur für falsch kalibrierte resistive Displays
            if cfg.TOUCH_SWAP_XY:
                tx, ty = ty, tx
            if cfg.TOUCH_INVERT_X:
                tx = W - tx
            if cfg.TOUCH_INVERT_Y:
                ty = H - ty
        # Touch-Menü hat Priorität wenn es offen ist
        if self._touch_menu_open:
            self._touch_touch_menu(tx, ty)
            return

        state = self._scanner.status_dict()["state"]
        if state == "MENU":
            self._touch_menu(tx, ty)
        elif state == "BANK_SELECT":
            self._touch_bank(tx, ty)
        elif state == "BT_SETUP":
            self._touch_bt(tx, ty)
        elif state in ("IDLE", "SCANNING", "ACTIVE"):
            # Klick auf Hauptansicht → Touch-Menü öffnen
            self._touch_menu_open = True
            self._draw()

    def _touch_menu(self, tx: int, ty: int):
        """Menü-Overlay Touch – gleiche Koordinaten wie _draw_menu_overlay."""
        OX, OY = 30, 40
        OW, OH = W - 60, H - 70
        items  = self._get_menu_items()
        avail  = OH - 38 - 28
        item_h = min(34, avail // max(len(items), 1))
        for i in range(len(items)):
            iy = OY + 38 + i * item_h
            if self._hit(tx, ty, OX + 8, iy, OW - 16, item_h - 4):
                self._menu_idx = i
                self._menu_select()
                return

    def _touch_bt(self, tx: int, ty: int):
        """BT-Wizard Touch – Back-Button und Listeneinträge."""
        # Back/Close-Button (unten links, alle Phasen außer CONNECTING/REMOVING)
        phase = self._bt_phase
        if phase not in ("CONNECTING", "REMOVING"):
            if self._hit(tx, ty, self._BT_BACK_X, self._BT_BACK_Y,
                         self._BT_BACK_W, self._BT_BACK_H):
                if phase == "ERROR":
                    # Erneut suchen statt Zurück
                    self._bt_wizard_active = False
                    self._bt_start_scan()
                else:
                    self.bt_back()
                return

        # Listeneinträge antouchen (PAIRED-Phase)
        OX, OY = self._BT_OX, self._BT_OY
        OW, OH = self._BT_OW, self._BT_OH
        if phase == "PAIRED":
            item_h  = 30
            max_vis = 4
            start   = max(0, min(self._bt_paired_cursor - 1,
                                  len(self._bt_paired_devices) - max_vis))
            for slot in range(max_vis):
                di = start + slot
                if di >= len(self._bt_paired_devices):
                    break
                iy = OY + 34 + slot * item_h
                if self._hit(tx, ty, OX + 6, iy, OW - 12, item_h - 3):
                    self._bt_paired_cursor   = di
                    self._bt_paired_selected = self._bt_paired_devices[di]
                    self._bt_detail_cursor   = 0
                    self._bt_phase           = "PAIRED_DETAIL"
                    self._draw()
                    return
            # "+ Neues Gerät"-Button
            add_y = OY + 34 + max_vis * item_h + 4
            if self._hit(tx, ty, OX + 6, add_y, OW - 12, item_h - 3):
                self._bt_start_scan()
                return

        elif phase == "PAIRED_DETAIL":
            dev       = self._bt_paired_selected
            is_active = (dev is not None and
                         self._scanner.bt.connected_address == dev.address)
            for i in range(2):
                iy = OY + 96 + i * 44
                if self._hit(tx, ty, OX + 20, iy, OW - 40, 32):
                    self._bt_detail_cursor = i
                    self.bt_confirm()
                    return

        elif phase in ("SELECT", "DONE"):
            self.bt_confirm()

    def _touch_bank(self, tx: int, ty: int):
        """Bank-Select Touch – gleiche Koordinaten wie _draw_bank_overlay."""
        from core.buttons import ButtonEvent
        OX, OY = 20, 34
        OW     = W - 40
        cell_w = (OW - 20) // 5
        cell_h = 44
        for i in range(10):
            col_i = i % 5
            row_i = i // 5
            bx = OX + 10 + col_i * cell_w
            by = OY + 36 + row_i * (cell_h + 6)
            if self._hit(tx, ty, bx, by, cell_w - 4, cell_h):
                self._scanner.banks.set_active_bank(i)
                self._scanner.buttons.inject(ButtonEvent.BANK_LOAD)
                self._scanner.buttons.inject(ButtonEvent.ENC_PRESS)
                return


    def _handle_key(self, key):
        from core.buttons import ButtonEvent
        pg    = self._pg
        state = self._scanner.status_dict()["state"]

        # Im Menü: Cursor mit Pfeiltasten, Enter = Auswahl
        if state == "MENU":
            if   key == pg.K_UP:     self._menu_up()
            elif key == pg.K_DOWN:   self._menu_down()
            elif key == pg.K_RETURN: self._menu_select()
            elif key == pg.K_ESCAPE: self._scanner.buttons.inject(ButtonEvent.MENU)
            return

        # Bank-Select: Pfeile wechseln Bank, Enter lädt
        if state == "BANK_SELECT":
            if   key == pg.K_RIGHT:  self._scanner.buttons.inject(ButtonEvent.ENC_UP)
            elif key == pg.K_LEFT:   self._scanner.buttons.inject(ButtonEvent.ENC_DOWN)
            elif key == pg.K_RETURN: self._scanner.buttons.inject(ButtonEvent.ENC_PRESS)
            elif key == pg.K_ESCAPE: self._scanner.buttons.inject(ButtonEvent.MENU)
            return

        # Normalbetrieb
        mapping = {
            pg.K_SPACE:  ButtonEvent.SCAN_TOGGLE,
            pg.K_m:      ButtonEvent.MODE,
            pg.K_s:      ButtonEvent.MEMORY,
            pg.K_UP:     ButtonEvent.SQ_UP,
            pg.K_DOWN:   ButtonEvent.SQ_DOWN,
            pg.K_RIGHT:  ButtonEvent.ENC_UP,
            pg.K_LEFT:   ButtonEvent.ENC_DOWN,
            pg.K_RETURN: ButtonEvent.ENC_PRESS,
            pg.K_TAB:    ButtonEvent.MENU,       # Tab öffnet Menü
        }
        if key in mapping:
            self._scanner.buttons.inject(mapping[key])

        # Im Menü-Modus muss der Scanner auch ENC_UP/DOWN für
        # die Cursor-Bewegung im Overlay verwenden – wir leiten
        # ENC_UP/DOWN im MENU-State auf _menu_up/_menu_down um.
        # Das passiert in scanner.py via on_state_change nicht,
        # daher hängen wir hier einen extra Hook rein:
        if state == "MENU" and key in (pg.K_RIGHT, pg.K_LEFT):
            return   # schon oben behandelt

