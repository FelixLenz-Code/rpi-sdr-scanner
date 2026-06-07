#!/bin/bash
# Baut das sdr-scanner .deb-Paket.
# Aufruf: bash packaging/build_deb.sh [VERSION]
# Ergebnis: dist/sdr-scanner_VERSION_arm64.deb
set -e

VERSION="${1:-1.0.0}"
PKG="sdr-scanner_${VERSION}_arm64"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STAGING="${PROJECT_DIR}/dist/${PKG}"

echo "[build_deb] Version: ${VERSION}"
echo "[build_deb] Staging: ${STAGING}"

# ── Altes Staging bereinigen ───────────────────────────────────────────────
rm -rf "${STAGING}"

# ── Verzeichnisstruktur anlegen ────────────────────────────────────────────
mkdir -p "${STAGING}/DEBIAN"
mkdir -p "${STAGING}/usr/share/sdr-scanner"
mkdir -p "${STAGING}/lib/systemd/system"
mkdir -p "${STAGING}/usr/bin"

# ── App-Dateien kopieren (ohne packaging/, case/, dist/, Caches) ──────────
rsync -a \
    --exclude='packaging/' \
    --exclude='case/' \
    --exclude='dist/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='bookmarks.db' \
    --exclude='.git/' \
    "${PROJECT_DIR}/" \
    "${STAGING}/usr/share/sdr-scanner/"

# ── systemd-Services ───────────────────────────────────────────────────────
cp "${PROJECT_DIR}/sdr_scanner.service" \
    "${STAGING}/lib/systemd/system/sdr_scanner.service"

cp "${SCRIPT_DIR}/sdr_hotspot.service" \
    "${STAGING}/lib/systemd/system/sdr_hotspot.service"

# ── DEBIAN-Metadaten ───────────────────────────────────────────────────────
cp "${SCRIPT_DIR}/debian/control"    "${STAGING}/DEBIAN/control"
cp "${SCRIPT_DIR}/debian/postinst"   "${STAGING}/DEBIAN/postinst"
cp "${SCRIPT_DIR}/debian/prerm"      "${STAGING}/DEBIAN/prerm"
cp "${SCRIPT_DIR}/debian/conffiles"  "${STAGING}/DEBIAN/conffiles"

# Version in control eintragen
sed -i "s/^Version: .*/Version: ${VERSION}/" "${STAGING}/DEBIAN/control"

# ── Berechtigungen setzen ──────────────────────────────────────────────────
chmod 755 "${STAGING}/DEBIAN/postinst"
chmod 755 "${STAGING}/DEBIAN/prerm"

# ── .deb bauen ─────────────────────────────────────────────────────────────
dpkg-deb --build --root-owner-group "${STAGING}"

DEB_FILE="${PROJECT_DIR}/dist/${PKG}.deb"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Fertig: ${DEB_FILE}"
echo "  Größe:  $(du -sh "${DEB_FILE}" | cut -f1)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Installation auf dem Pi:"
echo "    sudo dpkg -i ${PKG}.deb"
echo "    sudo apt-get install -f    # fehlende Deps nachholen"
echo ""
