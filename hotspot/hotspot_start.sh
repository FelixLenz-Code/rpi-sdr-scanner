#!/bin/bash
# hotspot/hotspot_start.sh
# Wird von sdr_hotspot.service beim Start aufgerufen.
# Startet hostapd + dnsmasq sauber in der richtigen Reihenfolge.

IFACE="wlan0"
IP="192.168.4.1"
LOG="logger -t sdr_hotspot"

$LOG "Starte WLAN-Hotspot..."

# RF-Kill entfernen (NetworkManager soft-blockiert WiFi wenn kein WLAN konfiguriert)
rfkill unblock wifi 2>/dev/null || /usr/sbin/rfkill unblock wifi 2>/dev/null || true
$LOG "rfkill: WiFi unblocked"

# NetworkManager anweisen wlan0 freizugeben, damit hostapd direkten Zugriff bekommt
if command -v nmcli > /dev/null 2>&1; then
    nmcli dev set "$IFACE" managed no 2>/dev/null || true
    $LOG "NetworkManager: wlan0 unmanaged"
fi

# wpa_supplicant für wlan0 stoppen (blockiert sonst hostapd)
systemctl stop "wpa_supplicant@${IFACE}.service" 2>/dev/null || true
wpa_cli -i "$IFACE" terminate 2>/dev/null || true
sleep 0.5

# wlan0 auf statische IP bringen
ip link set "$IFACE" up
ip addr flush dev "$IFACE" 2>/dev/null || true
ip addr add "${IP}/24" dev "$IFACE" 2>/dev/null || true

# dnsmasq starten
systemctl start dnsmasq
$LOG "dnsmasq gestartet"

# hostapd starten (braucht kurze Pause nach IP-Zuweisung)
sleep 1
systemctl start hostapd
$LOG "hostapd gestartet"

# iptables Redirect Port 80 → 5000 (falls nach Reboot weg)
iptables -t nat -C PREROUTING -i "${IFACE}" -p tcp --dport 80 \
    -j REDIRECT --to-port 5000 2>/dev/null || \
iptables -t nat -A PREROUTING -i "${IFACE}" -p tcp --dport 80 \
    -j REDIRECT --to-port 5000

$LOG "Hotspot bereit: SSID=$(grep '^ssid=' /etc/hostapd/hostapd.conf | cut -d= -f2)"
