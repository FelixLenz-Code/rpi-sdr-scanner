#!/bin/bash
# Startet den Scanner mit automatisch erkanntem SPI-Framebuffer.
# Sucht das fb-Device mit fb_ili9486 im Namen; fällt auf /dev/fb0 zurück.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Richtige Framebuffer-Device finden
FB=/dev/fb0
for d in /sys/class/graphics/fb*; do
    if grep -qi "ili9486\|fb_ili" "$d/name" 2>/dev/null; then
        FB="/dev/$(basename "$d")"
        break
    fi
done

echo "[start_scanner] SDL_FBDEV=$FB"

# Bluetooth-Adapter entsperren und hochbringen
rfkill unblock bluetooth 2>/dev/null || true
hciconfig hci1 up 2>/dev/null || hciconfig hci0 up 2>/dev/null || true

# PulseAudio-Socket explizit auf den User-Session-Socket zeigen.
# Ohne XDG_RUNTIME_DIR startet Python eine zweite PA-Instanz, die den BT-Sink nicht kennt.
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export PULSE_RUNTIME_PATH="${XDG_RUNTIME_DIR}/pulse"

# PA starten / reparieren (stale Socket → kill + restart)
if ! pactl info >/dev/null 2>&1; then
    pulseaudio --kill 2>/dev/null || true
    rm -f "${PULSE_RUNTIME_PATH}/native" "${PULSE_RUNTIME_PATH}/pid" 2>/dev/null
    sleep 0.3
    pulseaudio --start --daemonize=yes --exit-idle-time=-1 2>/dev/null || true
    sleep 1
fi

export SDL_AUDIODRIVER=dummy
export PYTHONUNBUFFERED=1
export TSLIB_TSDEVICE=/dev/input/touchscreen
export SDL_MOUSEDEV=/dev/input/touchscreen
export SDL_MOUSEDRV=TSLIB

exec /usr/bin/python3 "$SCRIPT_DIR/main.py" --web
