#!/usr/bin/env python3
"""Boot-Splash für das SPI-Display (480×320). Läuft als sdr_splash.service."""
import os, sys, time, math

os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
os.environ.setdefault("SDL_FBDEV",       "/dev/fb1")
os.environ.setdefault("SDL_NOMOUSE",     "1")

import pygame as pg

W, H = 480, 320

BG      = (10,  12,  20)
PRIMARY = (0,  200, 160)
DIM     = (30,  45,  60)
MUTED   = (80, 100, 120)
WHITE   = (220, 230, 240)

def _font(size):
    return pg.font.SysFont("monospace", size, bold=True)

def _wave(surf, cx, cy, t):
    """Animierte Sinuswelle als Frequenz-Symbol."""
    pts = []
    for i in range(80):
        x = cx - 39 + i
        phase = (i / 79.0) * math.pi * 4 - t * 4
        amp   = 14 * math.sin(phase) * math.exp(-((i - 39) ** 2) / (2 * 25 ** 2))
        pts.append((x, int(cy + amp)))
    if len(pts) > 1:
        pg.draw.lines(surf, PRIMARY, False, pts, 2)

def main():
    pg.init()
    try:
        screen = pg.display.set_mode((W, H), pg.NOFRAME)
    except Exception:
        sys.exit(0)

    pg.mouse.set_visible(False)
    clock = pg.time.Clock()

    f_big   = _font(44)
    f_med   = _font(18)
    f_small = _font(13)

    title1 = f_big.render("SDR",     True, PRIMARY)
    title2 = f_big.render("Scanner", True, WHITE)
    sub    = f_med.render("Raspberry Pi · RTL-SDR · 1-DIN", True, MUTED)

    t_start = time.monotonic()
    t = 0.0

    while True:
        for ev in pg.event.get():
            if ev.type == pg.QUIT:
                pg.quit(); return

        screen.fill(BG)

        # Hintergrund-Raster
        for x in range(0, W, 40):
            pg.draw.line(screen, DIM, (x, 0), (x, H), 1)
        for y in range(0, H, 40):
            pg.draw.line(screen, DIM, (0, y), (W, y), 1)

        # Leuchtender Akzentbalken oben
        pg.draw.rect(screen, PRIMARY, (0, 0, W, 3))

        # Wellenform-Symbol
        _wave(screen, W // 2, 95, t)

        # Titel
        x1 = W // 2 - (title1.get_width() + title2.get_width() + 12) // 2
        screen.blit(title1, (x1, 115))
        screen.blit(title2, (x1 + title1.get_width() + 12, 115))

        # Untertitel
        screen.blit(sub, (W // 2 - sub.get_width() // 2, 172))

        # Ladebalken
        elapsed = time.monotonic() - t_start
        DURATION = 4.0
        progress = min(elapsed / DURATION, 1.0)
        BAR_W, BAR_H = 280, 4
        bx = (W - BAR_W) // 2
        by = 230
        pg.draw.rect(screen, DIM,     (bx, by, BAR_W, BAR_H), border_radius=2)
        pg.draw.rect(screen, PRIMARY, (bx, by, int(BAR_W * progress), BAR_H), border_radius=2)

        # "Starte…"-Text
        dot_count = int(elapsed * 2) % 4
        loading = f_small.render("Starte" + "." * dot_count, True, MUTED)
        screen.blit(loading, (W // 2 - loading.get_width() // 2, 248))

        # Unterer Akzentbalken
        pg.draw.rect(screen, DIM, (0, H - 3, W, 3))

        pg.display.flip()
        t += clock.tick(30) / 1000.0

        if elapsed >= DURATION:
            break

    # Sanftes Ausblenden
    fade = pg.Surface((W, H))
    fade.fill(BG)
    for alpha in range(0, 256, 16):
        fade.set_alpha(alpha)
        screen.blit(fade, (0, 0))
        pg.display.flip()
        pg.time.wait(16)

    pg.quit()

if __name__ == "__main__":
    main()
