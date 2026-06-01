#!/bin/bash
# hotspot/hotspot_start.sh
# Wird von sdr_hotspot.service beim Start aufgerufen.
# Startet hostapd + dnsmasq sauber in der richtigen Reihenfolge.

IFACE="wlan0"
IP="192.168.4.1"
LOG="logger -t sdr_hotspot"

$LOG "Starte WLAN-Hotspot..."

# wlan0 auf statische IP bringen (falls dhcpcd noch nicht fertig)
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
