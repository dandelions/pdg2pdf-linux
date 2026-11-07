#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VERSION=$(sed -n 's/^pdg2pdf-linux (\([^)]*\)).*/\1/p' "$ROOT/debian/changelog" | cut -d- -f1)
ARCH=$(dpkg --print-architecture)
PKG="pdg2pdf-linux_${VERSION}_${ARCH}"
STAGE="$ROOT/../$PKG"
OUT="$ROOT/../${PKG}.deb"

rm -rf "$STAGE" "$OUT"
install -d "$STAGE/DEBIAN" "$STAGE/usr/lib/pdg2pdf/pdg2pdf" \
  "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/doc/pdg2pdf-linux"

cp -a "$ROOT/pdg2pdf/"*.py "$STAGE/usr/lib/pdg2pdf/pdg2pdf/"
install -m 644 "$ROOT/pdg2pdf.py" "$STAGE/usr/lib/pdg2pdf/pdg2pdf.py"
install -m 755 "$ROOT/debian/pdg2pdf" "$STAGE/usr/bin/pdg2pdf"
install -m 755 "$ROOT/debian/pdg2pdf-gui" "$STAGE/usr/bin/pdg2pdf-gui"
install -m 644 "$ROOT/debian/pdg2pdf-linux.desktop" "$STAGE/usr/share/applications/pdg2pdf-linux.desktop"
install -m 644 "$ROOT/README.md" "$STAGE/usr/share/doc/pdg2pdf-linux/README.md"
install -m 644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/pdg2pdf-linux/copyright"
install -m 644 "$ROOT/THIRD_PARTY_NOTICES.md" "$STAGE/usr/share/doc/pdg2pdf-linux/THIRD_PARTY_NOTICES.md"
install -m 644 "$ROOT/UPSTREAM_LICENSE" "$STAGE/usr/share/doc/pdg2pdf-linux/UPSTREAM_LICENSE"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: pdg2pdf-linux
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: dandelions <helium-ci@localhost>
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, python3-pil, python3-img2pdf, python3-pikepdf, djvulibre-bin
Description: native Linux PDG book converter
 Convert PDG books to PDF without Wine. Includes CLI and GTK3 desktop application.
EOF

dpkg-deb --build --root-owner-group "$STAGE" "$OUT"
rm -rf "$STAGE"
printf 'Built %s\n' "$OUT"
