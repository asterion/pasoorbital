#!/usr/bin/env bash
# Construye el paquete .deb de PasoOrbital para GNOME.
set -euo pipefail
umask 022
cd "$(dirname "$0")"

PKG=pasoorbital
VERSION=1.7.0
ARCH=all
STAGE="$PWD/build/${PKG}_${VERSION}-1_${ARCH}"
DIST="$PWD/dist"
DEST="$STAGE/usr/lib/python3/dist-packages"

rm -rf "$PWD/build"
mkdir -p "$STAGE/DEBIAN" "$STAGE/usr/bin" "$DEST/pasoorbital" "$DEST/pasoorbital_gui"
mkdir -p "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps" \
         "$STAGE/usr/share/metainfo" \
         "$STAGE/usr/share/doc/pasoorbital"
mkdir -p "$DIST"

# Motor PasoOrbital y aplicación GTK
cp ../pasoorbital/*.py "$DEST/pasoorbital/"
cp pasoorbital_gui/*.py pasoorbital_gui/style.css "$DEST/pasoorbital_gui/"
mkdir -p "$DEST/pasoorbital_gui/assets"
cp pasoorbital_gui/assets/* "$DEST/pasoorbital_gui/assets/"

# Lanzador
cat > "$STAGE/usr/bin/pasoorbital-gui" <<'PYEOF'
#!/usr/bin/python3
# -*- coding: utf-8 -*-
from pasoorbital_gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
PYEOF
chmod 755 "$STAGE/usr/bin/pasoorbital-gui"

# Permisos legibles para todos (los ficheros fuente pueden venir con 600)
find "$DEST" -type d -exec chmod 755 {} +
find "$DEST" -type f -exec chmod 644 {} +

# Página de manual
mkdir -p "$STAGE/usr/share/man/man1"
gzip -9n -c pasoorbital-gui.1 > "$STAGE/usr/share/man/man1/pasoorbital-gui.1.gz"
chmod 644 "$STAGE/usr/share/man/man1/pasoorbital-gui.1.gz"

# Integración con el escritorio
install -m 644 io.github.asterion.PasoOrbital.desktop "$STAGE/usr/share/applications/io.github.asterion.PasoOrbital.desktop"
install -m 644 io.github.asterion.PasoOrbital.svg "$STAGE/usr/share/icons/hicolor/scalable/apps/io.github.asterion.PasoOrbital.svg"
install -m 644 io.github.asterion.PasoOrbital.metainfo.xml "$STAGE/usr/share/metainfo/io.github.asterion.PasoOrbital.metainfo.xml"
install -m 644 ../README.md "$STAGE/usr/share/doc/pasoorbital/README.md"
install -m 644 ../LICENSE "$STAGE/usr/share/doc/pasoorbital/copyright"
install -m 644 ../AUTHORS.md "$STAGE/usr/share/doc/pasoorbital/AUTHORS.md"
install -m 644 README.md "$STAGE/usr/share/doc/pasoorbital/README.desktop.md"
gzip -9n -c > "$STAGE/usr/share/doc/pasoorbital/changelog.Debian.gz" <<'CHANGELOG'
pasoorbital (1.7.0-1) unstable; urgency=medium

  * Primera versión de escritorio para GNOME (GTK4 + libadwaita).

 -- Marcos Matamala Fernandez <asterion@users.noreply.github.com>  Sat, 17 Oct 2026 00:00:00 +0000
CHANGELOG

# Control del paquete
INSTALLED_SIZE=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: ${VERSION}-1
Architecture: $ARCH
Maintainer: Marcos Matamala Fernandez <asterion@users.noreply.github.com>
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0 (>= 4.10), gir1.2-gdkpixbuf-2.0, gir1.2-adw-1 (>= 1.6), python3-numpy, python3-sgp4 (>= 2.22)
Section: science
Priority: optional
Homepage: https://github.com/asterion/pasoorbital
Description: predicción de pasos de satélites para escucha radio
 PasoOrbital calcula qué satélites pasan por tu ubicación, con hora, altura,
 dirección, duración, frecuencia de escucha y efecto Doppler.
 .
 Incluye un resumen en lenguaje llano de cada paso, gráficos de la
 trayectoria en el cielo y comandos listos para copiar para RTL-SDR,
 SatDump o noaa-apt.
EOF

# Scripts de mantenimiento
cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk4-update-icon-cache >/dev/null 2>&1; then
  gtk4-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF
cp "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

# Sumas de verificación
(cd "$STAGE" && find usr -type f -print0 | sort -z | xargs -0 md5sum > DEBIAN/md5sums)

# Construcción
dpkg-deb --build --root-owner-group "$STAGE" "$DIST/${PKG}_${VERSION}-1_${ARCH}.deb"

echo
echo "Paquete generado: $DIST/${PKG}_${VERSION}-1_${ARCH}.deb"
dpkg-deb -I "$DIST/${PKG}_${VERSION}-1_${ARCH}.deb" | sed -n '1,25p'
