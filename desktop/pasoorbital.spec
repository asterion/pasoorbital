Name:           pasoorbital
Version:        1.9.0
Release:        1
Summary:        Predicción de pasos de satélites para escucha radio
License:        MIT
URL:            https://github.com/asterion/pasoorbital
Source0:        pasoorbital-%{version}.tar.gz
BuildArch:      noarch
AutoReqProv:    no

Requires:       python3 >= 3.10
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita >= 1.6
Requires:       gdk-pixbuf2
Requires:       python3-numpy
Requires:       python3-sgp4

%description
PasoOrbital calcula qué satélites pasan por tu ubicación, con hora, altura,
dirección, duración, frecuencia de escucha y efecto Doppler.

Incluye una app GTK4/libadwaita con resumen en lenguaje llano, gráficos de la
trayectoria, comandos para RTL-SDR, SatDump o noaa-apt, avisos de escritorio y
un detalle modal con pestañas Resumen, Radio y Cielo.

%prep
%autosetup -n pasoorbital-%{version}

%build
python3 -m compileall -q pasoorbital desktop/pasoorbital_gui

%install
rm -rf %{buildroot}
install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{python3_sitelib}
install -d %{buildroot}%{_datadir}/applications
install -d %{buildroot}%{_datadir}/metainfo
install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -d %{buildroot}%{_mandir}/man1

cp -a pasoorbital %{buildroot}%{python3_sitelib}/
cp -a desktop/pasoorbital_gui %{buildroot}%{python3_sitelib}/
find %{buildroot}%{python3_sitelib} -type d -name __pycache__ -prune -exec rm -rf {} +
find %{buildroot}%{python3_sitelib} -name '*.pyc' -delete

cat > %{buildroot}%{_bindir}/pasoorbital <<'EOF'
#!/usr/bin/python3
# -*- coding: utf-8 -*-
from pasoorbital.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
EOF
chmod 755 %{buildroot}%{_bindir}/pasoorbital

cat > %{buildroot}%{_bindir}/pasoorbital-gui <<'EOF'
#!/usr/bin/python3
# -*- coding: utf-8 -*-
from pasoorbital_gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
EOF
chmod 755 %{buildroot}%{_bindir}/pasoorbital-gui

install -m644 desktop/io.github.asterion.PasoOrbital.desktop \
  %{buildroot}%{_datadir}/applications/io.github.asterion.PasoOrbital.desktop
install -m644 desktop/io.github.asterion.PasoOrbital.metainfo.xml \
  %{buildroot}%{_datadir}/metainfo/io.github.asterion.PasoOrbital.metainfo.xml
install -m644 desktop/io.github.asterion.PasoOrbital.svg \
  %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.asterion.PasoOrbital.svg
install -m644 desktop/pasoorbital-gui.1 \
  %{buildroot}%{_mandir}/man1/pasoorbital-gui.1

%post
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || :
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || :
fi

%postun
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || :
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || :
fi

%files
%{_bindir}/pasoorbital
%{_bindir}/pasoorbital-gui
%{python3_sitelib}/pasoorbital/
%{python3_sitelib}/pasoorbital_gui/
%{_datadir}/applications/io.github.asterion.PasoOrbital.desktop
%{_datadir}/metainfo/io.github.asterion.PasoOrbital.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/io.github.asterion.PasoOrbital.svg
%{_mandir}/man1/pasoorbital-gui.1*
%license LICENSE
%doc README.md AUTHORS.md

%changelog
* Sun Oct 18 2026 Marcos Matamala Fernandez <asterion@users.noreply.github.com> - 1.9.0-1
- Cielo en vivo con marcador, estela y progreso del paso.
- Paquete RPM instalable con rpm.
