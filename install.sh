#!/bin/bash
# =============================================================================
#  install.sh — Vollständige Installation des RPi SDR Scanners
#  Raspberry Pi Zero 2 W · Raspberry Pi OS Lite 64-bit (Debian 12 Bookworm)
#
#  Aufruf (als normaler pi-User, NICHT als root):
#    bash install.sh
#
#  Optionen:
#    --no-display    Kein Waveshare-Display-Treiber installieren
#    --no-hotspot    Keinen WLAN-Hotspot einrichten
#    --no-service    Keinen systemd-Service installieren
#    --debug         Mehr Ausgaben
# =============================================================================

set -euo pipefail

# ── Optionen parsen ────────────────────────────────────────────────────────────
OPT_DISPLAY=true
OPT_HOTSPOT=true
OPT_SERVICE=true
OPT_DEBUG=false

OPT_REBOOT=true

for arg in "$@"; do
  case "$arg" in
    --no-display) OPT_DISPLAY=false ;;
    --no-hotspot) OPT_HOTSPOT=false ;;
    --no-service) OPT_SERVICE=false ;;
    --no-reboot)  OPT_REBOOT=false  ;;
    --debug)      OPT_DEBUG=true    ;;
  esac
done

# Im firstrun-Modus: alle interaktiven Fragen automatisch beantworten
if [ "${FIRSTRUN_MODE:-0}" = "1" ]; then
  OPT_REBOOT=false
  # Hotspot-Defaults aus Umgebung oder fest
  HOTSPOT_SSID="${FIRSTRUN_SSID:-SDR-Scanner}"
  HOTSPOT_PASS="${FIRSTRUN_PASS:-sdrscanner}"
fi

# ── Farben & Ausgabe ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

step()  { echo -e "\n${BOLD}${CYAN}▶  $*${NC}"; }
ok()    { echo -e "   ${GREEN}✓${NC}  $*"; }
warn()  { echo -e "   ${YELLOW}⚠${NC}  $*"; }
error() { echo -e "\n${RED}✗  Fehler: $*${NC}\n"; exit 1; }
info()  { echo -e "   ${NC}·  $*"; }
debug() { $OPT_DEBUG && echo -e "   [debug] $*" || true; }

# ── Konfiguration ─────────────────────────────────────────────────────────────
INSTALL_DIR="/home/pi/sdr_scanner"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="python3"
PIP="pip3"
RTL_BLACKLIST="/etc/modprobe.d/blacklist-rtl.conf"
SERVICE_FILE="/etc/systemd/system/sdr_scanner.service"
HOTSPOT_SERVICE="/etc/systemd/system/sdr_hotspot.service"

# Hotspot-Defaults (änderbar in Abschnitt 7)
HOTSPOT_SSID="SDR-Scanner"
HOTSPOT_PASS="sdrscanner"
HOTSPOT_IP="192.168.4.1"
HOTSPOT_CHANNEL=6

# ══════════════════════════════════════════════════════════════════════════════
#  BANNER
# ══════════════════════════════════════════════════════════════════════════════

echo -e "${BOLD}"
echo "  ┌─────────────────────────────────────────────────┐"
echo "  │         RPi SDR Scanner – Installation          │"
echo "  │   Raspberry Pi Zero 2 W · NooElec NESDR SMArt   │"
echo "  └─────────────────────────────────────────────────┘"
echo -e "${NC}"
echo -e "  Installationsverzeichnis: ${CYAN}${INSTALL_DIR}${NC}"
echo -e "  Display-Treiber:          $(${OPT_DISPLAY} && echo 'ja' || echo 'nein')"
echo -e "  WLAN-Hotspot:             $(${OPT_HOTSPOT} && echo 'ja' || echo 'nein')"
echo -e "  systemd-Service:          $(${OPT_SERVICE} && echo 'ja' || echo 'nein')"
echo ""
if [ "${FIRSTRUN_MODE:-0}" = "1" ]; then
  echo "  [firstrun] Automatisch bestätigt."
else
  read -rp "  Fortfahren? [j/N] " CONFIRM
  [[ "$CONFIRM" =~ ^[jJyY] ]] || { echo "Abgebrochen."; exit 0; }
fi

# ══════════════════════════════════════════════════════════════════════════════
#  1. VORAUSSETZUNGEN PRÜFEN
# ══════════════════════════════════════════════════════════════════════════════

step "Voraussetzungen prüfen"

# Nicht als root ausführen
[ "$EUID" -ne 0 ] || error "Bitte als normaler Nutzer ausführen (nicht sudo). Das Script fragt selbst nach sudo wenn nötig."

# Betriebssystem prüfen
if [ -f /etc/os-release ]; then
  . /etc/os-release
  debug "OS: $PRETTY_NAME"
  [[ "$ID" == "raspbian" || "$ID" == "debian" ]] || \
    warn "Nicht-Debian-System erkannt ($ID) – Probleme möglich"
else
  warn "Kann Betriebssystem nicht ermitteln"
fi

# Python-Version
PY_VER=$($PY --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
[ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ] || \
  error "Python 3.10+ benötigt, gefunden: $PY_VER"
ok "Python $PY_VER"

# Installationsverzeichnis
[ -d "$SCRIPT_DIR/core" ] || \
  error "Script muss aus dem sdr_scanner-Verzeichnis gestartet werden (core/ nicht gefunden)"
ok "Installationsverzeichnis gefunden: $SCRIPT_DIR"

# Sudo-Zugriff testen
sudo -n true 2>/dev/null || {
  warn "Sudo-Passwort wird benötigt"
  sudo true || error "Kein Sudo-Zugriff"
}
ok "Sudo verfügbar"

# ══════════════════════════════════════════════════════════════════════════════
#  2. SYSTEM-PAKETE
# ══════════════════════════════════════════════════════════════════════════════

step "System-Pakete installieren"
info "apt update läuft..."

sudo apt-get update -qq 2>&1 | tail -1 || warn "apt update mit Fehlern"

PACKAGES=(
  # SDR
  rtl-sdr
  # Audio
  pulseaudio
  pulseaudio-utils
  pulseaudio-module-bluetooth
  libportaudio2
  alsa-utils
  # Bluetooth
  bluez
  bluez-tools
  python3-dbus
  python3-gi
  # Display
  python3-pygame
  # Python
  python3-pip
  python3-gpiozero
  python3-flask
  python3-requests
  python3-numpy
  python3-scipy
  python3-lgpio
  python3-pyaudio
  # Netz
  hostapd
  dnsmasq
  iptables
  # Kalibrierung
  kalibrate-rtl
  # TTS – pico2wave (primär) + RHVoice (Fallback)
  libttspico-utils
  rhvoice
  rhvoice-english
  # Hilfsmittel
  git
  unzip
  curl
  libusb-1.0-0
)

info "Installiere: ${PACKAGES[*]}"
sudo apt-get install -y --no-install-recommends "${PACKAGES[@]}" \
  2>&1 | grep -E '(Setting up|already|error)' | while read -r l; do info "$l"; done

ok "System-Pakete installiert"

# ══════════════════════════════════════════════════════════════════════════════
#  3. PYTHON-PAKETE
# ══════════════════════════════════════════════════════════════════════════════

step "Python-Pakete installieren"

PY_PACKAGES=(
  "pyrtlsdr"   # RTL-SDR direkte Bibliothek (pip-Version neuer als apt)
  "lgpio"      # Encoder-Hardware-Zugriff
  "RPi.GPIO"   # GPIO-Fallback
)

for pkg in "${PY_PACKAGES[@]}"; do
  if $PIP show "$pkg" &>/dev/null; then
    debug "$pkg bereits installiert"
  else
    info "Installiere $pkg..."
    $PIP install "$pkg" --break-system-packages -q || \
      warn "$pkg konnte nicht installiert werden"
  fi
done

ok "Python-Pakete installiert"

# ══════════════════════════════════════════════════════════════════════════════
#  4. RTL-SDR KONFIGURIEREN
# ══════════════════════════════════════════════════════════════════════════════

step "RTL-SDR konfigurieren"

# Kernel-Treiber blacklisten (verhindert dass dvb_usb den Dongle übernimmt)
if ! grep -q "dvb_usb_rtl28xxu" "$RTL_BLACKLIST" 2>/dev/null; then
  sudo tee "$RTL_BLACKLIST" > /dev/null << 'EOF'
# RTL-SDR: Standard DVB-USB-Treiber deaktivieren
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
EOF
  ok "RTL-SDR Blacklist geschrieben"
else
  ok "RTL-SDR Blacklist bereits vorhanden"
fi

# udev-Regel: Pi-User darf den Dongle ohne root nutzen
UDEV_RULE='/etc/udev/rules.d/20-rtlsdr.rules'
if [ ! -f "$UDEV_RULE" ]; then
  sudo tee "$UDEV_RULE" > /dev/null << 'EOF'
# RTL-SDR USB-Dongle: Zugriff für Gruppe "plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", GROUP="plugdev", MODE="0664"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", GROUP="plugdev", MODE="0664"
# NooElec NESDR SMArt
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", GROUP="plugdev", MODE="0664"
EOF
  sudo udevadm control --reload-rules
  ok "udev-Regel für RTL-SDR gesetzt"
fi

# User zur plugdev-Gruppe hinzufügen
if ! groups | grep -q "plugdev"; then
  sudo usermod -aG plugdev "$USER"
  ok "User $USER zur Gruppe plugdev hinzugefügt"
fi

# SPI für Display aktivieren
if ! grep -q "dtparam=spi=on" /boot/config.txt 2>/dev/null && \
   ! grep -q "dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null; then
  BOOT_CFG="/boot/firmware/config.txt"
  [ -f "$BOOT_CFG" ] || BOOT_CFG="/boot/config.txt"
  echo "dtparam=spi=on" | sudo tee -a "$BOOT_CFG" > /dev/null
  ok "SPI aktiviert in $BOOT_CFG"
else
  ok "SPI bereits aktiviert"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  4b. BLUETOOTH KONFIGURIEREN
# ══════════════════════════════════════════════════════════════════════════════

step "Bluetooth konfigurieren"

# Bluetooth-Service aktivieren
sudo systemctl enable bluetooth 2>/dev/null || true

# PulseAudio BT-Module in default.pa eintragen (falls noch nicht vorhanden)
PA_CONF="/etc/pulse/default.pa"
if [ -f "$PA_CONF" ]; then
  grep -q "module-bluetooth-discover" "$PA_CONF" 2>/dev/null || {
    sudo tee -a "$PA_CONF" > /dev/null << 'EOF'

# Bluetooth A2DP
load-module module-bluetooth-policy
load-module module-bluetooth-discover
EOF
    ok "PulseAudio BT-Module eingetragen"
  }
  ok "PulseAudio BT bereits konfiguriert"
else
  warn "PulseAudio default.pa nicht gefunden – BT-Audio manuell konfigurieren"
fi

# User zur bluetooth-Gruppe (D-Bus Zugriff)
if ! groups | grep -q "\bbluetooth\b"; then
  sudo usermod -aG bluetooth "$USER"
  ok "User $USER zur Gruppe bluetooth hinzugefügt"
else
  ok "User $USER bereits in Gruppe bluetooth"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  5. SCANNER-SOFTWARE INSTALLIEREN
# ══════════════════════════════════════════════════════════════════════════════

step "Scanner-Software installieren"

# Zielverzeichnis anlegen falls nötig
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
  info "Kopiere nach $INSTALL_DIR..."
  mkdir -p "$INSTALL_DIR"
  cp -r "$SCRIPT_DIR"/. "$INSTALL_DIR/"
  ok "Dateien nach $INSTALL_DIR kopiert"
else
  ok "Bereits im Installationsverzeichnis"
fi

# Datenbank-Verzeichnis + Rechte
mkdir -p "$INSTALL_DIR"
touch "$INSTALL_DIR/bookmarks.db" 2>/dev/null || true
chmod 755 "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/hotspot/"*.sh 2>/dev/null || true

ok "Verzeichnisstruktur bereit"

# ══════════════════════════════════════════════════════════════════════════════
#  6. DISPLAY-TREIBER (Waveshare 3,5" IPS)
# ══════════════════════════════════════════════════════════════════════════════

if $OPT_DISPLAY; then
  step "MHS 3,5\" Display-Treiber einrichten (ILI9486 / XPT2046)"

  BOOT_CFG="/boot/firmware/config.txt"
  [ -f "$BOOT_CFG" ] || BOOT_CFG="/boot/config.txt"

  # User zur video-Gruppe hinzufügen (Zugriff auf /dev/fb1)
  if ! groups | grep -q "\bvideo\b"; then
    sudo usermod -aG video "$USER"
    ok "User $USER zur Gruppe video hinzugefügt"
  else
    ok "User $USER bereits in Gruppe video"
  fi

  # Display-Overlay konfigurieren (ILI9486, waveshare35a-kompatibel)
  if grep -q "dtoverlay=waveshare35\|dtoverlay=MHS35\|dtoverlay=ili9486" "$BOOT_CFG" 2>/dev/null; then
    ok "Display-Overlay bereits konfiguriert"
  else
    info "Konfiguriere MHS35/ILI9486 Overlay in $BOOT_CFG..."
    sudo tee -a "$BOOT_CFG" > /dev/null << 'EOF'

# MHS 3.5" SPI Display (ILI9486 Controller, XPT2046 Touch)
# waveshare35a ist kompatibel: gleicher Chip + GPIO-Pinout
dtoverlay=waveshare35a,speed=27000000,rotate=90
EOF
    ok "Display-Overlay eingetragen (waveshare35a / ILI9486, 90°)"
  fi

  # Headless: ohne HDMI-Monitor würde /dev/fb0=SPI statt /dev/fb1 sein
  if ! grep -q "hdmi_force_hotplug" "$BOOT_CFG" 2>/dev/null; then
    echo "hdmi_force_hotplug=1" | sudo tee -a "$BOOT_CFG" > /dev/null
    ok "hdmi_force_hotplug=1 gesetzt → SPI bleibt auf /dev/fb1"
  else
    ok "hdmi_force_hotplug bereits gesetzt"
  fi

  # tslib für resistiven Touchscreen installieren
  sudo apt-get install -y --no-install-recommends tslib libts-dev evtest -qq 2>/dev/null || \
    warn "tslib nicht installierbar – Touchscreen eventuell ohne Kalibrierung"

  TSLIB_CONF="/etc/ts.conf"
  if [ ! -f "$TSLIB_CONF" ]; then
    sudo tee "$TSLIB_CONF" > /dev/null << 'EOF'
module_raw input
module pthres pmin=1
module dejitter delta=100
module linear
EOF
    ok "tslib konfiguriert"
  fi

  TS_ENV="/etc/environment"
  grep -q "TSLIB_TSDEVICE" "$TS_ENV" 2>/dev/null || {
    echo 'TSLIB_TSDEVICE=/dev/input/touchscreen' | sudo tee -a "$TS_ENV" > /dev/null
    echo 'SDL_MOUSEDEV=/dev/input/touchscreen'   | sudo tee -a "$TS_ENV" > /dev/null
    echo 'SDL_MOUSEDRV=TSLIB'                    | sudo tee -a "$TS_ENV" > /dev/null
    ok "Touch-Umgebungsvariablen gesetzt"
  }

  info "Touchscreen-Kalibrierung: Nach Neustart einmalig 'sudo ts_calibrate' ausführen"

else
  info "Display-Treiber übersprungen (--no-display)"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  7. WLAN-HOTSPOT EINRICHTEN
# ══════════════════════════════════════════════════════════════════════════════

if $OPT_HOTSPOT; then
  step "WLAN-Hotspot konfigurieren"

  # SSID / Passwort – interaktiv oder automatisch
  if [ "${FIRSTRUN_MODE:-0}" = "1" ]; then
    info "Firstrun-Modus: SSID='${HOTSPOT_SSID}', Passwort='${HOTSPOT_PASS}'"
  else
    echo ""
    echo -e "  ${BOLD}Hotspot-Konfiguration${NC}"
    read -rp "  WLAN-Name (SSID) [${HOTSPOT_SSID}]: " INPUT_SSID
    HOTSPOT_SSID="${INPUT_SSID:-$HOTSPOT_SSID}"

    while true; do
      read -rsp "  Passwort (min. 8 Zeichen) [${HOTSPOT_PASS}]: " INPUT_PASS; echo
      INPUT_PASS="${INPUT_PASS:-$HOTSPOT_PASS}"
      [ ${#INPUT_PASS} -ge 8 ] && { HOTSPOT_PASS="$INPUT_PASS"; break; }
      warn "Passwort zu kurz – mindestens 8 Zeichen"
    done
  fi

  info "SSID: $HOTSPOT_SSID  |  IP: $HOTSPOT_IP"

  # hostapd konfigurieren
  sudo tee /etc/hostapd/hostapd.conf > /dev/null << EOF
interface=wlan0
driver=nl80211
ssid=${HOTSPOT_SSID}
hw_mode=g
channel=${HOTSPOT_CHANNEL}
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${HOTSPOT_PASS}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
country_code=DE
EOF

  # hostapd Daemon-Config
  HOSTAPD_DEFAULT="/etc/default/hostapd"
  sudo sed -i 's|#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' \
    "$HOSTAPD_DEFAULT" 2>/dev/null || \
    echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' | sudo tee -a "$HOSTAPD_DEFAULT" > /dev/null

  # dnsmasq konfigurieren
  [ -f /etc/dnsmasq.conf.orig ] || sudo cp /etc/dnsmasq.conf /etc/dnsmasq.conf.orig
  sudo tee /etc/dnsmasq.conf > /dev/null << EOF
interface=wlan0
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,24h
domain=local
address=/scanner.local/${HOTSPOT_IP}
address=/#/${HOTSPOT_IP}
dhcp-option=option:router,${HOTSPOT_IP}
dhcp-option=option:dns-server,${HOTSPOT_IP}
no-resolv
no-poll
EOF

  # Statische IP für wlan0
  DHCPCD_CONF="/etc/dhcpcd.conf"
  if ! grep -q "interface wlan0" "$DHCPCD_CONF" 2>/dev/null; then
    sudo tee -a "$DHCPCD_CONF" > /dev/null << EOF

# SDR Scanner Hotspot
interface wlan0
    static ip_address=${HOTSPOT_IP}/24
    nohook wpa_supplicant
EOF
    ok "Statische IP für wlan0 gesetzt"
  fi

  # iptables: HTTP-Port 80 → Web-UI Port 5000
  sudo iptables -t nat -C PREROUTING -i wlan0 -p tcp --dport 80 \
    -j REDIRECT --to-port 5000 2>/dev/null || \
  sudo iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 80 \
    -j REDIRECT --to-port 5000 2>/dev/null || warn "iptables-Redirect nicht gesetzt"

  # iptables persistent speichern
  sudo apt-get install -y --no-install-recommends iptables-persistent -qq 2>/dev/null && \
    sudo netfilter-persistent save 2>/dev/null || \
    sudo iptables-save | sudo tee /etc/iptables/rules.v4 > /dev/null 2>/dev/null || \
    warn "iptables-Regeln nicht persistent gespeichert – nach Reboot evtl. neu setzen"

  # sdr_hotspot.service schreiben
  sudo tee "$HOTSPOT_SERVICE" > /dev/null << EOF
[Unit]
Description=SDR Scanner WLAN Hotspot
After=network.target
Before=sdr_scanner.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash ${INSTALL_DIR}/hotspot/hotspot_start.sh
ExecStop=/bin/bash ${INSTALL_DIR}/hotspot/hotspot_stop.sh

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl unmask hostapd 2>/dev/null || true
  sudo systemctl enable sdr_hotspot
  sudo systemctl enable hostapd
  sudo systemctl enable dnsmasq

  ok "Hotspot konfiguriert: SSID='${HOTSPOT_SSID}'"
  info "Erreichbar nach Reboot unter: http://${HOTSPOT_IP}:5000 oder http://scanner.local"

else
  info "Hotspot übersprungen (--no-hotspot)"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  8. SYSTEMD-SERVICE
# ══════════════════════════════════════════════════════════════════════════════

if $OPT_SERVICE; then
  step "systemd-Service installieren"

  sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=RPi SDR Tischscanner
After=network.target sound.target sdr_hotspot.service
Wants=sdr_hotspot.service

[Service]
Type=simple
User=${USER}
WorkingDirectory=${INSTALL_DIR}
ExecStartPre=/bin/bash -c 'for i in \$(seq 1 30); do ls /dev/fb* >/dev/null 2>&1 && exit 0; sleep 0.5; done; exit 1'
ExecStart=/bin/bash ${INSTALL_DIR}/start_scanner.sh
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
KillMode=control-group
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable sdr_scanner
  ok "Service aktiviert: sdr_scanner.service"

else
  info "Service übersprungen (--no-service)"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  9. AUDIO KONFIGURIEREN
# ══════════════════════════════════════════════════════════════════════════════

step "Audio konfigurieren"

# PulseAudio als System-Service oder User-Service?
# Beim Zero 2 W User-Service verwenden
PULSE_CONF_DIR="/home/${USER}/.config/pulse"
mkdir -p "$PULSE_CONF_DIR"

# PulseAudio: Automatisch starten
PULSE_CLIENT="${PULSE_CONF_DIR}/client.conf"
cat > "$PULSE_CLIENT" << 'EOF'
autospawn = yes
daemon-binary = /usr/bin/pulseaudio
EOF

# Lautsprecher-Test-Skript
cat > "${INSTALL_DIR}/test_audio.sh" << 'EOF'
#!/bin/bash
# Kurzer Audiotest – erzeugt einen 1-kHz-Ton
echo "Audiotest (1 kHz, 2 Sekunden)..."
speaker-test -t sine -f 1000 -l 1 2>/dev/null || \
  aplay /usr/share/sounds/alsa/Front_Center.wav 2>/dev/null || \
  echo "Kein Ausgabegerät – Audio manuell prüfen"
EOF
chmod +x "${INSTALL_DIR}/test_audio.sh"

ok "Audio-Konfiguration gesetzt"

# ══════════════════════════════════════════════════════════════════════════════
#  10. SCHNELL-TESTS
# ══════════════════════════════════════════════════════════════════════════════

step "Kurztest der Installation"

TESTS_PASSED=0
TESTS_FAILED=0

run_test() {
  local desc="$1"; local cmd="$2"
  if eval "$cmd" &>/dev/null; then
    ok "$desc"
    (( TESTS_PASSED++ )) || true
  else
    warn "$desc – FEHLGESCHLAGEN"
    (( TESTS_FAILED++ )) || true
  fi
}

run_test "Python 3 vorhanden"            "$PY --version"
run_test "rtl_fm vorhanden"              "command -v rtl_fm"
run_test "rtl_test vorhanden"            "command -v rtl_test"
run_test "flask importierbar"            "$PY -c 'import flask'"
run_test "pygame importierbar"           "SDL_VIDEODRIVER=dummy $PY -c 'import pygame; pygame.display.init()'"
run_test "gpiozero importierbar"         "$PY -c 'import gpiozero' 2>/dev/null || true"
run_test "Scanner-main.py vorhanden"     "[ -f ${INSTALL_DIR}/main.py ]"
run_test "config/settings.py vorhanden" "[ -f ${INSTALL_DIR}/config/settings.py ]"
run_test "SQLite-DB beschreibbar"        "touch ${INSTALL_DIR}/bookmarks.db"
$OPT_HOTSPOT && run_test "hostapd vorhanden" "command -v hostapd"
$OPT_HOTSPOT && run_test "dnsmasq vorhanden" "command -v dnsmasq"

# RTL-SDR Dongle: nur prüfen wenn angeschlossen
if lsusb 2>/dev/null | grep -qi "0bda:2838\|0bda:2832\|realtek"; then
  run_test "RTL-SDR Dongle erkannt" "rtl_test -t 2>&1 | grep -q 'Found'"
else
  info "RTL-SDR Dongle nicht angeschlossen – Dongle-Test übersprungen"
fi

echo ""
echo -e "  Tests: ${GREEN}${TESTS_PASSED} bestanden${NC}  |  ${RED}${TESTS_FAILED} fehlgeschlagen${NC}"

# ══════════════════════════════════════════════════════════════════════════════
#  11. ABSCHLUSS
# ══════════════════════════════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}${GREEN}"
echo "  ╔═════════════════════════════════════════════════╗"
echo "  ║   Installation abgeschlossen!                   ║"
echo "  ╚═════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "  ${BOLD}Nächste Schritte:${NC}"
echo ""
echo -e "  ${CYAN}1.${NC} Neu starten (für Display-Treiber und Hotspot):"
echo -e "     ${BOLD}sudo reboot${NC}"
echo ""
if $OPT_HOTSPOT; then
  echo -e "  ${CYAN}2.${NC} Nach Neustart:"
  echo -e "     WLAN '${HOTSPOT_SSID}' erscheint nach ~30 Sekunden"
  echo -e "     Verbinden mit Passwort: ${BOLD}${HOTSPOT_PASS}${NC}"
  echo -e "     Browser: ${CYAN}http://scanner.local${NC}  oder  ${CYAN}http://${HOTSPOT_IP}:5000${NC}"
  echo ""
  echo -e "  ${CYAN}3.${NC} Display prüfen: SPI-Device vorhanden?"
  echo -e "     ${BOLD}ls /dev/fb*${NC}   (fb1 = SPI-Display aktiv)"
  echo ""
  echo -e "  ${CYAN}4.${NC} Touchscreen kalibrieren (einmalig nach Reboot):"
  echo -e "     ${BOLD}sudo ts_calibrate${NC}"
  echo ""
  echo -e "  ${CYAN}5.${NC} PPM-Kalibrierung in der Web-UI (Sidebar → Kalibrierung)"
  echo ""
  echo -e "  ${CYAN}6.${NC} WLAN-Passwort ändern (Sicherheit!):"
  echo -e "     ${BOLD}sudo bash ${INSTALL_DIR}/hotspot/change_wifi.sh${NC}"
fi
echo ""
echo -e "  ${BOLD}Manuell starten (ohne Neustart):${NC}"
echo -e "     cd ${INSTALL_DIR} && python3 main.py --web --debug"
echo ""
echo -e "  ${BOLD}Logs:${NC}"
echo -e "     journalctl -u sdr_scanner -f"
echo -e "     journalctl -u sdr_hotspot -f"
echo ""

# Reboot anbieten (nur wenn nicht --no-reboot)
if $OPT_REBOOT; then
  read -rp "  Jetzt neu starten? [j/N] " DO_REBOOT
  [[ "$DO_REBOOT" =~ ^[jJyY] ]] && sudo reboot || echo "  Bitte manuell neu starten: sudo reboot"
else
  echo "  Reboot wird vom aufrufenden Prozess durchgeführt."
fi
