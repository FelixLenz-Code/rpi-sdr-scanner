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

# Menüpunkte mit zugehörigem ButtonEvent-Namen
MENU_ITEMS = [
    ("Kalibrierung starten",   "CALIBRATE"),
    ("Bank umbenennen",        "MEMORY_LONG"),   # nutzt vorhandenen Flow
    ("Kanal sperren/freigeben","__LOCK__"),       # intern behandelt
    ("Menü schließen",         "__CLOSE__"),
]

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
            # HDMI-Modus: normaler Desktop-SDL-Output, kein Framebuffer
            os.environ.pop("SDL_VIDEODRIVER", None)   # SDL wählt selbst (x11/wayland/cocoa)
            os.environ.pop("SDL_FBDEV", None)
            os.environ.pop("SDL_NOMOUSE", None)
            log.info("HDMI-Modus: %dx%d (Skalierung %.2f×, Offset %d/%d)",
                     *self._hdmi_size, self._scale, self._ox, self._oy)
        elif not self._debug:
            os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
            os.environ.setdefault("SDL_FBDEV", "/dev/fb1")
            # Touch: SDL2 liest den resistiven Touchscreen als Maus-Device
            # Wenn SDL_NOMOUSE gesetzt ist, kommt kein MOUSEBUTTONDOWN.
            # Deshalb NOMOUSE nur setzen wenn Touch deaktiviert.
            if not cfg.TOUCH_ENABLED:
                os.environ.setdefault("SDL_NOMOUSE", "1")
            else:
                # Touchscreen-Device für SDL2 bekannt machen
                os.environ.setdefault("SDL_MOUSEDEV", "/dev/input/touchscreen")
                os.environ.setdefault("SDL_MOUSEDRV", "TSLIB")
                os.environ.setdefault("TSLIB_TSDEVICE", "/dev/input/touchscreen")

        pg.init()
        pg.mouse.set_visible(False)

        try:
            if self._hdmi:
                self._screen = pg.display.set_mode(self._hdmi_size, pg.RESIZABLE)
                pg.display.set_caption("SDR Scanner – HDMI Preview")
            else:
                self._screen = pg.display.set_mode(
                    (W, H),
                    pg.FULLSCREEN if not self._debug else 0,
                )
        except Exception as e:
            log.error("Display-Init fehlgeschlagen: %s", e)
            return

        pg.display.set_caption("SDR Scanner")
        self._load_fonts()
        clock = pg.time.Clock()

        while self._running:
            for ev in pg.event.get():
                if ev.type == pg.QUIT:
                    self._running = False
                elif ev.type == pg.KEYDOWN:
                    self._handle_key(ev.key)
                elif ev.type == pg.MOUSEBUTTONDOWN:
                    self._handle_touch(*ev.pos)
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
                self._screen.fill(BG)   # Letterbox-Hintergrund
                self._screen.blit(scaled, (self._ox, self._oy))
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
            if state == "MENU":
                self._draw_menu_overlay(s)
            elif state == "BANK_SELECT":
                self._draw_bank_overlay(s)
            elif state == "CALIBRATING":
                self._draw_calib_overlay(s)

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

        # Gruppe rechts
        self._text(s["group"], "small", (W - 10, 210), MUTED, anchor="mr")

        # ── Aktiv-Rahmen wenn Signal ──────────────────────────────────────
        if s["state"] == "ACTIVE":
            pg.draw.rect(scr, ACTIVE, (0, 0, W, H), 3)

        # ── Scan-Fortschrittsbalken ───────────────────────────────────────
        if s["state"] == "SCANNING":
            bw = int((s["ch_index"] / max(1, s["ch_total"])) * W)
            pg.draw.rect(scr, DIM,    (0,  H - 5, W,  5))
            pg.draw.rect(scr, SCAN_C, (0,  H - 5, bw, 5))

        # ── Hinweiszeile unten ────────────────────────────────────────────
        if s["state"] not in ("MENU", "BANK_SELECT"):
            if s["state"] == "ACTIVE":
                hint = "[ENC] Überspringen  [MEM] Speichern  [ENC lang] Menü"
            elif s["state"] == "SCANNING":
                hint = "[SCAN] Stop  [ENC] Lautstärke  [ENC lang] Menü"
            else:
                hint = "[SCAN] Start  [ENC] Kanal  [MEM lang] Bank  [ENC lang] Menü"
            self._text(hint, "tiny", (W // 2, H - 10), MUTED, anchor="mc")

    # ═════════════════════════════════════════════════════════════════════════
    #  MENÜ-OVERLAY
    # ═════════════════════════════════════════════════════════════════════════

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

        # Menüpunkte
        item_h = 34
        for i, (label, _) in enumerate(MENU_ITEMS):
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
        self._menu_idx = (self._menu_idx - 1) % len(MENU_ITEMS)

    def _menu_down(self):
        self._menu_idx = (self._menu_idx + 1) % len(MENU_ITEMS)

    def _menu_select(self):
        from core.buttons import ButtonEvent
        _, action = MENU_ITEMS[self._menu_idx]

        if action == "__CLOSE__":
            self._scanner.buttons.inject(ButtonEvent.MENU)

        elif action == "__LOCK__":
            # Aktuellen Kanal in aktiver Bank sperren/freigeben
            ch = self._scanner.freq.current
            if ch:
                s = self._scanner.banks
                # Slot des aktuellen Kanals in aktiver Bank suchen
                for mem_ch in s.list_bank():
                    if mem_ch.freq == ch.freq and mem_ch.mode == ch.mode:
                        s.toggle_lock(mem_ch.bank, mem_ch.slot)
                        ch.locked = not ch.locked
                        break

        else:
            self._scanner.buttons.inject(ButtonEvent[action])

        if action != "__CLOSE__":
            self._scanner.buttons.inject(ButtonEvent.MENU)

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
        state = self._scanner.status_dict()["state"]
        if state == "MENU":
            self._touch_menu(tx, ty)
        elif state == "BANK_SELECT":
            self._touch_bank(tx, ty)

    def _touch_menu(self, tx: int, ty: int):
        """Menü-Overlay Touch – gleiche Koordinaten wie _draw_menu_overlay."""
        OX, OY = 30, 40
        OW     = W - 60
        item_h = 34
        for i in range(len(MENU_ITEMS)):
            iy = OY + 38 + i * item_h
            if self._hit(tx, ty, OX + 8, iy, OW - 16, item_h - 4):
                self._menu_idx = i
                self._menu_select()
                return

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

    # Wird von scanner.py aufgerufen wenn ENC_UP/DOWN im MENU-State kommt
    def menu_cursor_up(self):
        self._menu_idx = (self._menu_idx - 1) % len(MENU_ITEMS)

    def menu_cursor_down(self):
        self._menu_idx = (self._menu_idx + 1) % len(MENU_ITEMS)

    def menu_confirm(self):
        self._menu_select()
