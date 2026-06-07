#!/usr/bin/env python3
"""Boot-Splash für das SPI-Display (480×320). Läuft als sdr_splash.service."""
import os, sys, time, math, glob

W, H = 480, 320

BG      = (10,  12,  20)
PRIMARY = (0,  200, 160)
DIM     = (30,  45,  60)
MUTED   = (80, 100, 120)
WHITE   = (220, 230, 240)


def _find_fb() -> str | None:
    for d in sorted(glob.glob('/sys/class/graphics/fb*')):
        try:
            name = open(f'{d}/name').read().strip().lower()
            if 'ili9486' in name or 'fb_ili' in name:
                return f'/dev/{os.path.basename(d)}'
        except OSError:
            pass
    # fallback: /dev/fb1 wenn kein ILI9486-Eintrag gefunden
    if os.path.exists('/dev/fb1'):
        return '/dev/fb1'
    return None


def _write_fb(fb_file, np, surface, pg):
    arr = pg.surfarray.array3d(surface).transpose(1, 0, 2)
    r = arr[:, :, 0].astype(np.uint16) >> 3
    g = arr[:, :, 1].astype(np.uint16) >> 2
    b = arr[:, :, 2].astype(np.uint16) >> 3
    rgb565 = (r << 11) | (g << 5) | b
    fb_file.seek(0)
    fb_file.write(rgb565.tobytes())


def _font(pg, size):
    return pg.font.SysFont("monospace", size, bold=True)


def _wave(surf, pg, cx, cy, t):
    pts = []
    for i in range(80):
        x = cx - 39 + i
        phase = (i / 79.0) * math.pi * 4 - t * 4
        amp   = 14 * math.sin(phase) * math.exp(-((i - 39) ** 2) / (2 * 25 ** 2))
        pts.append((x, int(cy + amp)))
    if len(pts) > 1:
        pg.draw.lines(surf, PRIMARY, False, pts, 2)


def main():
    # Warten bis Framebuffer bereit ist (SPI-Treiber lädt nach Kernel)
    fb_path = None
    for _ in range(150):
        fb_path = _find_fb()
        if fb_path:
            break
        time.sleep(0.2)
    if not fb_path:
        sys.exit(0)

    try:
        import numpy as np
        fb_file = open(fb_path, 'wb')
    except Exception:
        sys.exit(0)

    # Offscreen-Rendering – kein SDL-Treiber nötig, kein Audio
    os.environ['SDL_VIDEODRIVER'] = 'offscreen'
    os.environ['SDL_AUDIODRIVER'] = 'dummy'
    os.environ.pop('SDL_FBDEV', None)
    os.environ['SDL_NOMOUSE'] = '1'

    import pygame as pg

    pg.display.init()
    pg.font.init()
    try:
        screen = pg.display.set_mode((W, H))
    except Exception:
        fb_file.close()
        sys.exit(0)

    pg.mouse.set_visible(False)
    clock = pg.time.Clock()

    f_big   = _font(pg, 44)
    f_med   = _font(pg, 18)
    f_small = _font(pg, 13)

    title1 = f_big.render("SDR",     True, PRIMARY)
    title2 = f_big.render("Scanner", True, WHITE)
    sub    = f_med.render("Raspberry Pi · RTL-SDR · SPI-Display", True, MUTED)

    READY_FLAG = "/tmp/sdr-scanner-ready"
    TIMEOUT    = 90.0

    t_start = time.monotonic()
    t = 0.0

    while True:
        for ev in pg.event.get():
            if ev.type == pg.QUIT:
                break

        elapsed = time.monotonic() - t_start
        if os.path.exists(READY_FLAG) or elapsed >= TIMEOUT:
            break

        screen.fill(BG)

        for x in range(0, W, 40):
            pg.draw.line(screen, DIM, (x, 0), (x, H), 1)
        for y in range(0, H, 40):
            pg.draw.line(screen, DIM, (0, y), (W, y), 1)

        pg.draw.rect(screen, PRIMARY, (0, 0, W, 3))

        _wave(screen, pg, W // 2, 95, t)

        x1 = W // 2 - (title1.get_width() + title2.get_width() + 12) // 2
        screen.blit(title1, (x1, 115))
        screen.blit(title2, (x1 + title1.get_width() + 12, 115))

        screen.blit(sub, (W // 2 - sub.get_width() // 2, 172))

        dot_count = int(elapsed * 2) % 4
        loading = f_small.render("Starte" + "." * dot_count, True, MUTED)
        screen.blit(loading, (W // 2 - loading.get_width() // 2, 230))

        pg.draw.rect(screen, DIM, (0, H - 3, W, 3))

        _write_fb(fb_file, np, screen, pg)

        t += clock.tick(30) / 1000.0

    fb_file.close()
    pg.display.quit()
    pg.font.quit()


if __name__ == "__main__":
    main()
