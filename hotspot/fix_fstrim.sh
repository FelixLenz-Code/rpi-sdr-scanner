#!/bin/bash
# fix_fstrim.sh – fstrim auf dem Pi deaktivieren
# Ausführen wenn der Pi per SSH erreichbar ist
#
# Lokal ausführen:    sudo bash fix_fstrim.sh
# Per SSH ausführen:  ssh pi@192.168.4.1 'sudo bash /home/pi/sdr_scanner/hotspot/fix_fstrim.sh'

set -e
echo "Deaktiviere fstrim.service und fstrim.timer..."

systemctl disable fstrim.service 2>/dev/null && echo "  fstrim.service disabled" || true
systemctl disable fstrim.timer   2>/dev/null && echo "  fstrim.timer disabled"   || true
systemctl mask    fstrim.service 2>/dev/null && echo "  fstrim.service masked"   || true
systemctl mask    fstrim.timer   2>/dev/null && echo "  fstrim.timer masked"     || true

# Auch in der fstab: noatime und nodiscard setzen damit SD-Karte schonend behandelt wird
if grep -q ' discard' /etc/fstab; then
    sed -i 's/,discard//g; s/discard,//g' /etc/fstab
    echo "  fstab: discard-Option entfernt"
fi

echo ""
echo "Fertig. fstrim wird beim nächsten Boot nicht mehr ausgeführt."
