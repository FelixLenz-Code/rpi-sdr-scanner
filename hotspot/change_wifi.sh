#!/bin/bash
# hotspot/change_wifi.sh
# SSID und Passwort des Hotspots ändern.
#
# Aufruf:
#   sudo bash change_wifi.sh "Mein Scanner" "meinpasswort"
#   oder interaktiv ohne Argumente

set -e

HOSTAPD_CONF="/etc/hostapd/hostapd.conf"
[ -f "$HOSTAPD_CONF" ] || { echo "hostapd nicht eingerichtet. setup_hotspot.sh zuerst ausführen."; exit 1; }
[ "$EUID" -eq 0 ]      || { echo "Bitte als root ausführen."; exit 1; }

if [ -n "$1" ]; then
    NEW_SSID="$1"
else
    read -rp "Neuer WLAN-Name (SSID): " NEW_SSID
fi

if [ -n "$2" ]; then
    NEW_PASS="$2"
else
    read -rsp "Neues Passwort (min. 8 Zeichen): " NEW_PASS; echo
fi

# Validierung
[ ${#NEW_SSID} -ge 1 ] && [ ${#NEW_SSID} -le 32 ] || \
    { echo "SSID muss 1–32 Zeichen lang sein."; exit 1; }
[ ${#NEW_PASS} -ge 8 ] || \
    { echo "Passwort muss mindestens 8 Zeichen lang sein."; exit 1; }

# Konfiguration aktualisieren
sed -i "s|^ssid=.*|ssid=${NEW_SSID}|"          "$HOSTAPD_CONF"
sed -i "s|^wpa_passphrase=.*|wpa_passphrase=${NEW_PASS}|" "$HOSTAPD_CONF"

echo "Konfiguration aktualisiert."
echo "Starte Hotspot neu..."
systemctl restart hostapd

echo "Fertig! Neuer Hotspot:"
echo "  SSID:    ${NEW_SSID}"
echo "  Passwort: ${NEW_PASS}"
