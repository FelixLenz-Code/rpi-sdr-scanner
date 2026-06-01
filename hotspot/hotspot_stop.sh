#!/bin/bash
# hotspot/hotspot_stop.sh
# Wird von sdr_hotspot.service beim Stopp aufgerufen.

IFACE="wlan0"
LOG="logger -t sdr_hotspot"

$LOG "Stoppe WLAN-Hotspot..."

systemctl stop hostapd  2>/dev/null || true
systemctl stop dnsmasq  2>/dev/null || true

# iptables-Regel entfernen
iptables -t nat -D PREROUTING -i "${IFACE}" -p tcp --dport 80 \
    -j REDIRECT --to-port 5000 2>/dev/null || true

$LOG "Hotspot gestoppt."
