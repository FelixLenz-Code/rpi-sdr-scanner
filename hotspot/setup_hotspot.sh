#!/bin/bash
# hotspot/setup_hotspot.sh
# Richtet einen WLAN-Hotspot auf dem Raspberry Pi ein.
# Der Pi ist danach unter 192.168.4.1:5000 erreichbar.
#
# Ausführen als root:  sudo bash setup_hotspot.sh
#
# Was dieses Script tut:
#   1. hostapd + dnsmasq installieren
#   2. Hotspot-Konfiguration schreiben
#   3. DHCP-Server konfigurieren
#   4. Statische IP für wlan0 setzen
#   5. systemd-Dienste aktivieren
#   6. Optional: Captive-Portal-Redirect (alle HTTP-Anfragen → Web-UI)

set -e

# ── Konfiguration ──────────────────────────────────────────────────────────────
SSID="SDR-Scanner"          # WLAN-Name
PASSPHRASE="sdrscanner"     # Mindestens 8 Zeichen (WPA2)
CHANNEL=6                   # 2,4-GHz-Kanal (1, 6 oder 11 empfohlen)
IP="192.168.4.1"            # IP des Pi im Hotspot-Netz
DHCP_START="192.168.4.10"   # Erster DHCP-Client
DHCP_END="192.168.4.50"     # Letzter DHCP-Client
IFACE="wlan0"               # WLAN-Interface (Zero 2 W hat nur wlan0)
WEB_PORT=5000               # Port der Flask Web-UI
SCANNER_DIR="${SCANNER_DIR:-/home/pi/sdr_scanner}"

# ── Farben für Ausgabe ─────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERR]${NC}   $*"; exit 1; }

# ── Root-Check ─────────────────────────────────────────────────────────────────
[ "$EUID" -eq 0 ] || error "Bitte als root ausführen: sudo bash $0"

# ── Interface prüfen ───────────────────────────────────────────────────────────
ip link show "$IFACE" > /dev/null 2>&1 || error "Interface $IFACE nicht gefunden."
info "Interface $IFACE gefunden."

# ── Pakete installieren ────────────────────────────────────────────────────────
# SKIP_APT=1 überspringt apt (z.B. wenn Pakete bereits via dpkg-Deps installiert)
if [ "${SKIP_APT:-0}" = "0" ]; then
    info "Installiere hostapd und dnsmasq..."
    apt-get update -qq
    apt-get install -y hostapd dnsmasq iptables
fi

# Dienste initial stoppen
systemctl stop hostapd 2>/dev/null || true
systemctl stop dnsmasq 2>/dev/null || true

# ── hostapd konfigurieren ──────────────────────────────────────────────────────
info "Konfiguriere hostapd..."
cat > /etc/hostapd/hostapd.conf << HOSTAPD_EOF
interface=${IFACE}
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=${CHANNEL}
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${PASSPHRASE}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
country_code=DE
HOSTAPD_EOF

# hostapd auf Konfigurationsdatei hinweisen
sed -i 's|#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' \
    /etc/default/hostapd 2>/dev/null || \
    echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' >> /etc/default/hostapd

# ── dnsmasq konfigurieren ──────────────────────────────────────────────────────
info "Konfiguriere dnsmasq (DHCP + DNS)..."

# Backup der Original-Konfiguration
[ -f /etc/dnsmasq.conf.orig ] || cp /etc/dnsmasq.conf /etc/dnsmasq.conf.orig

cat > /etc/dnsmasq.conf << DNSMASQ_EOF
# SDR Scanner Hotspot – DHCP + DNS
interface=${IFACE}
dhcp-range=${DHCP_START},${DHCP_END},255.255.255.0,24h
domain=local
address=/scanner.local/${IP}

# Captive-Portal: Alle DNS-Anfragen → Pi (damit Browser das Portal anzeigt)
address=/#/${IP}

# Lease-Zeit für schnelle Verbindung
dhcp-option=option:router,${IP}
dhcp-option=option:dns-server,${IP}

# Keine externe Auflösung nötig (Offline-Betrieb)
no-resolv
no-poll
DNSMASQ_EOF

# ── Statische IP für wlan0 ────────────────────────────────────────────────────
info "Setze statische IP für $IFACE..."

# dhcpcd-Konfiguration
DHCPCD_CONF="/etc/dhcpcd.conf"
if grep -q "interface ${IFACE}" "$DHCPCD_CONF" 2>/dev/null; then
    warn "Interface ${IFACE} bereits in dhcpcd.conf – überschreibe Block..."
    # Bestehenden Block entfernen
    sed -i "/^interface ${IFACE}/,/^$/d" "$DHCPCD_CONF"
fi

cat >> "$DHCPCD_CONF" << DHCPCD_EOF

# SDR Scanner Hotspot
interface ${IFACE}
    static ip_address=${IP}/24
    nohook wpa_supplicant
DHCPCD_EOF

# ── IP-Forwarding (optional, für Internet-Durchleitung) ───────────────────────
# Auskommentiert – im Standalone-Betrieb nicht nötig:
# echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-sdr-hotspot.conf

# ── iptables: Captive Portal Redirect ─────────────────────────────────────────
info "Richte Captive-Portal-Weiterleitung ein..."

# Alle HTTP-Anfragen an Port 80 → Web-UI Port
iptables -t nat -A PREROUTING -i "${IFACE}" -p tcp --dport 80 \
    -j REDIRECT --to-port "${WEB_PORT}" 2>/dev/null || \
    warn "iptables-Regel konnte nicht gesetzt werden (ggf. reboot nötig)"

# iptables-Regeln persistent speichern
if command -v iptables-save > /dev/null; then
    iptables-save > /etc/iptables/rules.v4 2>/dev/null || \
        iptables-save > /etc/iptables.rules 2>/dev/null || \
        warn "iptables-Regeln konnten nicht gespeichert werden"
fi

# ── systemd-Dienste vorbereiten (nicht auto-starten) ─────────────────────────
info "Vorbereite systemd-Dienste (kein Autostart)..."
systemctl unmask hostapd 2>/dev/null || true
systemctl unmask dnsmasq 2>/dev/null || true
systemctl disable hostapd 2>/dev/null || true
systemctl disable dnsmasq 2>/dev/null || true

# ── sdr_hotspot.service schreiben ─────────────────────────────────────────────
info "Schreibe sdr_hotspot.service..."
cat > /etc/systemd/system/sdr_hotspot.service << SERVICE_EOF
[Unit]
Description=SDR Scanner WLAN Hotspot
After=network.target
Before=sdr_scanner.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash ${SCANNER_DIR}/hotspot/hotspot_start.sh
ExecStop=/bin/bash ${SCANNER_DIR}/hotspot/hotspot_stop.sh

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl disable sdr_hotspot 2>/dev/null || true

# ── sdr_scanner.service: Web-UI erzwingen ─────────────────────────────────────
info "Aktiviere Web-UI im Scanner-Service..."
SCANNER_SERVICE="/etc/systemd/system/sdr_scanner.service"
if [ -f "$SCANNER_SERVICE" ]; then
    sed -i 's|ExecStart=.*main.py$|ExecStart=/usr/bin/python3 '"${SCANNER_DIR}"'/main.py --web|' \
        "$SCANNER_SERVICE"
    systemctl daemon-reload
fi

# ── Zusammenfassung ────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Hotspot-Einrichtung abgeschlossen!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  WLAN-Name:    ${SSID}"
echo "  Passwort:     ${PASSPHRASE}"
echo "  Pi-Adresse:   http://${IP}:${WEB_PORT}"
echo "  Kurzadresse:  http://scanner.local"
echo "  (HTTP-Port 80 wird automatisch weitergeleitet)"
echo ""
echo -e "${YELLOW}  Bitte neu starten: sudo reboot${NC}"
echo ""
