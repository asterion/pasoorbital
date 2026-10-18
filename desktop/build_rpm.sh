#!/usr/bin/env bash
# Construye un RPM instalable (sin repositorio dnf) para Fedora.
set -euo pipefail
cd "$(dirname "$0")"

SPEC="$PWD/pasoorbital.spec"
VERSION=$(awk '/^Version:/{print $2; exit}' "$SPEC")
RELEASE=$(awk '/^Release:/{print $2; exit}' "$SPEC")
ROOT=$(cd .. && pwd)
TOP="$PWD/build/rpm"
DIST="$PWD/dist"

RPMBUILD=${RPMBUILD:-rpmbuild}
if ! command -v "$RPMBUILD" >/dev/null 2>&1 && [ ! -x "$RPMBUILD" ]; then
    echo "Falta rpmbuild." >&2
    echo "En Fedora instala rpm-build; en Ubuntu, rpm." >&2
    exit 1
fi

rm -rf "$TOP"
mkdir -p "$TOP/BUILD" "$TOP/RPMS" "$TOP/SOURCES" "$TOP/SPECS" "$TOP/SRPMS" "$DIST"

# Fuente reproducible: solo lo necesario para el paquete.
tar -C "$ROOT" \
    --exclude=./.git \
    --exclude=./.venv \
    --exclude=./.tools \
    --exclude=./data \
    --exclude=./desktop/dist \
    --exclude=./desktop/build \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --transform "s,^\./,pasoorbital-$VERSION/," \
    -czf "$TOP/SOURCES/pasoorbital-$VERSION.tar.gz" .

cp "$SPEC" "$TOP/SPECS/pasoorbital.spec"

mkdir -p "$TOP/tmp" "$TOP/rpmdb"
extra=(--define "_tmppath $TOP/tmp" --define "_dbpath $TOP/rpmdb")
if [ -n "${PYTHON3_SITELIB:-}" ]; then
    extra+=(--define "python3_sitelib $PYTHON3_SITELIB")
fi

TMPDIR="$TOP/tmp" "$RPMBUILD" -bb --define "_topdir $TOP" "${extra[@]}" "$TOP/SPECS/pasoorbital.spec"

RPM="$TOP/RPMS/noarch/pasoorbital-$VERSION-$RELEASE.noarch.rpm"
if [ ! -f "$RPM" ]; then
    echo "No se generó el RPM esperado: $RPM" >&2
    exit 1
fi
cp "$RPM" "$DIST/"
echo
echo "RPM generado: $DIST/pasoorbital-$VERSION-$RELEASE.noarch.rpm"
