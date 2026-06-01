#!/usr/bin/env python3
# main.py – Einstiegspunkt für den SDR Scanner

import argparse
import logging
import signal
import sys
import threading

# ── Logging konfigurieren ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def parse_args():
    p = argparse.ArgumentParser(description="RPi SDR Tischscanner")
    p.add_argument("--debug", action="store_true",
                   help="Debug-Modus: kein GPIO, kein Framebuffer, rtl_fm simuliert")
    p.add_argument("--web",   action="store_true",
                   help="Web-UI auf Port 5000 starten")
    p.add_argument("--no-display", action="store_true",
                   help="Display-UI deaktivieren (nur für headless / Web-only)")
    p.add_argument("--hdmi", action="store_true",
                   help="HDMI-Ausgabe statt SPI-Display (skalierbares Fenster zum Testen)")
    p.add_argument("--hdmi-size", metavar="WxH", default="960x640",
                   help="HDMI-Fenstergrösse, z.B. 960x640 oder 1280x853 (default: 960x640)")
    return p.parse_args()


def main():
    args = parse_args()

    if args.debug:
        log.warning("Debug-Modus aktiv – GPIO und rtl_fm werden nicht genutzt")

    # Kein Display angeschlossen und kein HDMI-Modus → Display-UI deaktivieren
    # damit der Service nicht mit Fehlern stirbt
    if not args.no_display and not args.hdmi and not args.debug:
        import os
        fb_exists = os.path.exists("/dev/fb1") or os.path.exists("/dev/fb0")
        display_env = os.environ.get("DISPLAY", "")
        wayland_env = os.environ.get("WAYLAND_DISPLAY", "")
        if not fb_exists and not display_env and not wayland_env:
            log.warning("Kein Display-Device gefunden (/dev/fb0, /dev/fb1, DISPLAY, WAYLAND_DISPLAY) – Display-UI deaktiviert")
            log.warning("Starte mit --hdmi für HDMI-Ausgabe oder --no-display um diese Warnung zu unterdrücken")
            args.no_display = True

    # ── Scanner instanziieren ─────────────────────────────────────────────────
    from core.scanner import Scanner
    scanner = Scanner(debug=args.debug)

    # ── Display-UI ────────────────────────────────────────────────────────────
    display = None
    if not args.no_display:
        from ui.display import DisplayUI
        hdmi_size = None
        if args.hdmi:
            try:
                w, h = args.hdmi_size.lower().split("x")
                hdmi_size = (int(w), int(h))
            except Exception:
                log.warning("Ungültige --hdmi-size, verwende 960x640")
                hdmi_size = (960, 640)

        display = DisplayUI(scanner, debug=args.debug, hdmi=args.hdmi,
                            hdmi_size=hdmi_size)
        # Display-Referenz im Scanner hinterlegen (für Menü-Cursor-Routing)
        scanner._display_ref = display
        scanner.on_state_change = display._draw if display else lambda: None
        display.start()
        log.info("Display-UI gestartet")

    # ── Web-UI (optional) ─────────────────────────────────────────────────────
    if args.web:
        from ui.web import WebUI
        web = WebUI(scanner)
        web.start()
        log.info("Web-UI gestartet")

    # ── Scanner-Loop im Hauptthread ───────────────────────────────────────────
    # SIGTERM (von systemd/kill) in KeyboardInterrupt umwandeln, damit
    # scanner.run()'s finally-Block scanner.stop() aufruft und rtl_fm sauber beendet.
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        scanner.run()   # blockiert bis KeyboardInterrupt
    except KeyboardInterrupt:
        log.info("Beendet durch Benutzer")
    except Exception:
        log.exception("Unerwarteter Absturz")
    finally:
        if display:
            display.stop()
        log.info("Auf Wiedersehen")
        sys.exit(0)


if __name__ == "__main__":
    main()
