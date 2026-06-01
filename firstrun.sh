#!/bin/bash
# =============================================================================
#  firstrun.sh — Wird einmalig beim allerersten Boot ausgeführt (als root)
#
#  Einbetten: Diese Datei auf die Boot-Partition der SD-Karte kopieren
#  (dort wo cmdline.txt liegt, also /boot oder /boot/firmware)
#
#  Aktivieren: In cmdline.txt ans Ende anhängen (ALLES in einer Zeile):
#    systemd.run=/boot/firmware/firstrun.sh systemd.run_success_action=reboot
#
#  Das Script:
#   1. Wartet bis Netz und Zeit bereit sind
#   2. Aktualisiert das System
#   3. Entpackt sdr_scanner.zip von der Boot-Partition
#   4. Führt install.sh vollautomatisch aus
#   5. Löscht sich selbst und startet neu
#
#  Kein SSH, kein Einloggen, kein manueller Schritt nötig.
# =============================================================================

set -euo pipefail
exec > /boot/firmware/firstrun.log 2>&1   # Alle Ausgaben in Log-Datei

LOG="/boot/firmware/firstrun.log"
STAMP="/boot/firmware/firstrun.done"
ZIP_NAME="sdr_scanner.zip"
BOOT_DIR="/boot/firmware"
INSTALL_DIR="/home/pi/sdr_scanner"

# ── Nur einmal laufen ─────────────────────────────────────────────────────────
if [ -f "$STAMP" ]; then
  echo "[firstrun] Bereits ausgeführt – übersprungen."
  exit 0
fi

echo "================================================================="
echo "  SDR Scanner – Erstinstallation"
echo "  $(date)"
echo "================================================================="

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────
log()  { echo "[$(date +%H:%M:%S)] $*"; }
ok()   { echo "[$(date +%H:%M:%S)] ✓ $*"; }
fail() { echo "[$(date +%H:%M:%S)] ✗ FEHLER: $*"; exit 1; }

# ── 1. fstrim deaktivieren (hängt auf SD-Karten häufig) ──────────────────────
# Viele SD-Karten implementieren DISCARD/TRIM nicht korrekt → fstrim.service
# blockiert dann den Boot für Minuten bis zum Timeout.
log "Deaktiviere fstrim (SD-Karten-Kompatibilität)..."
systemctl disable fstrim.service  2>/dev/null || true
systemctl disable fstrim.timer    2>/dev/null || true
systemctl mask    fstrim.service  2>/dev/null || true
systemctl mask    fstrim.timer    2>/dev/null || true
ok "fstrim deaktiviert"

# ── 2. Auf systemd warten ─────────────────────────────────────────────────────
log "Warte auf systemd-Grunddienste..."
# Nicht --wait verwenden: das blockiert bis alle Units fertig sind,
# was bei langsamen SD-Karten lange dauern kann.
for i in $(seq 1 20); do
  STATE=$(systemctl is-system-running 2>/dev/null || echo "starting")
  case "$STATE" in
    running|degraded)
      ok "systemd bereit (Status: $STATE)"
      break
      ;;
  esac
  log "Warte... ($i/20) systemd=$STATE"
  sleep 3
done

# ── 3. Netzwerkzeit synchronisieren ───────────────────────────────────────────
log "Warte auf Zeitsynchro..."
for i in $(seq 1 30); do
  timedatectl show | grep -q "NTPSynchronized=yes" && break
  sleep 2
done
timedatectl show | grep -q "NTPSynchronized=yes" && \
  ok "Zeit synchronisiert: $(date)" || \
  log "Zeitsynchro nicht verfügbar – fahre trotzdem fort"

# ── 4. Hostname setzen ────────────────────────────────────────────────────────
log "Setze Hostname..."
hostnamectl set-hostname sdr-scanner
echo "127.0.1.1 sdr-scanner" >> /etc/hosts
ok "Hostname: sdr-scanner"

# ── 5. Passwort des pi-Users setzen ──────────────────────────────────────────
# Kann im Imager vorkonfiguriert werden – hier als Fallback
if ! getent passwd pi > /dev/null 2>&1; then
  log "User 'pi' nicht vorhanden – erstelle..."
  useradd -m -s /bin/bash -G sudo,audio,video,plugdev,gpio,spi,i2c pi
  echo "pi:raspberry" | chpasswd
  ok "User pi angelegt (Passwort: raspberry)"
else
  ok "User pi vorhanden"
fi

# ── 6. Paketindex aktualisieren ───────────────────────────────────────────────
log "apt update..."
apt-get update -qq 2>&1 | tail -2
ok "Paketliste aktuell"

# ── 7. unzip sicherstellen ────────────────────────────────────────────────────
command -v unzip > /dev/null || {
  log "Installiere unzip..."
  apt-get install -y unzip -qq
}

# ── 8. ZIP von Boot-Partition entpacken ───────────────────────────────────────
ZIP_PATH="${BOOT_DIR}/${ZIP_NAME}"
if [ ! -f "$ZIP_PATH" ]; then
  # Auch auf /boot (ältere Pi-OS-Versionen) suchen
  [ -f "/boot/${ZIP_NAME}" ] && ZIP_PATH="/boot/${ZIP_NAME}"
fi

[ -f "$ZIP_PATH" ] || fail "ZIP nicht gefunden: ${ZIP_PATH}
Bitte ${ZIP_NAME} auf die Boot-Partition der SD-Karte kopieren."

log "Entpacke ${ZIP_NAME}..."
mkdir -p /home/pi
cd /home/pi
unzip -q "$ZIP_PATH"
chown -R pi:pi /home/pi/sdr_scanner
ok "Entpackt nach ${INSTALL_DIR}"

# ── 9. install.sh vollautomatisch ausführen ───────────────────────────────────
log "Starte install.sh (automatisch, kein Reboot am Ende)..."

# Umgebungsvariablen für unbeaufsichtigten Betrieb
export DEBIAN_FRONTEND=noninteractive
export FIRSTRUN_MODE=1        # install.sh erkennt diesen Modus

# pygame-Test braucht kein echtes Display
export SDL_VIDEODRIVER=dummy

# Hardware erkennen: Display und SDR
HAS_DISPLAY=false
HAS_SDR=false
[ -e /dev/fb1 ] && HAS_DISPLAY=true
lsusb 2>/dev/null | grep -qi "0bda:2838\|0bda:2832" && HAS_SDR=true

log "Hardware-Erkennung: Display=$HAS_DISPLAY  SDR=$HAS_SDR"

# install.sh Flags je nach vorhandener Hardware
INSTALL_FLAGS="--no-reboot"
$HAS_DISPLAY || INSTALL_FLAGS="$INSTALL_FLAGS --no-display"

cd "$INSTALL_DIR"
echo "j" | bash install.sh $INSTALL_FLAGS 2>&1 | while read -r line; do
  echo "[install] $line"
done

ok "install.sh abgeschlossen"

# ── 9. Log und ZIP auf SD-Karte belassen (zur Fehlersuche) ────────────────────
cp "$LOG" "${INSTALL_DIR}/firstrun.log" 2>/dev/null || true

# ── 11. Abschluss-Markierung setzen ──────────────────────────────────────────
echo "$(date)" > "$STAMP"
ok "Erstinstallation abgeschlossen: $(date)"

# ── 11. cmdline.txt bereinigen (eigenen Eintrag entfernen) ───────────────────
log "Entferne firstrun-Eintrag aus cmdline.txt..."
CMDLINE="${BOOT_DIR}/cmdline.txt"
[ -f "$CMDLINE" ] || CMDLINE="/boot/cmdline.txt"
if [ -f "$CMDLINE" ]; then
  sed -i 's| systemd.run=/boot[^ ]*||g' "$CMDLINE"
  sed -i 's| systemd.run_success_action=[^ ]*||g' "$CMDLINE"
  ok "cmdline.txt bereinigt"
fi

echo "================================================================="
echo "  Erstinstallation fertig – Neustart in 5 Sekunden"
echo "  Nach dem Neustart: WLAN 'SDR-Scanner' verbinden"
echo "  Browser: http://scanner.local oder http://192.168.4.1:5000"
echo "================================================================="
sleep 5
reboot
