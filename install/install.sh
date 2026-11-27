#!/bin/bash
# STL2STEP - installatie BINNEN de container (Debian 12/13), als root.
# Wordt door stl2step.sh aangeroepen, maar kan ook los vanuit een kloon van de repo:
#     bash install/install.sh
# Opnieuw uitvoeren = bijwerken.
set -euo pipefail

export LANG=C.UTF-8 LC_ALL=C.UTF-8
echo "LANG=C.UTF-8" > /etc/default/locale

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../src" && pwd)"
[ -f "$SRC/convert.py" ] || { echo "Bronbestanden niet gevonden in $SRC"; exit 1; }
GEBRUIKER=cad
DATA=/srv/cad
APP=/opt/stl2step
POORT=8080
MET_SAMBA=${MET_SAMBA:-"nee"}
PWBESTAND=/root/.stl2step-smbpw     # gebruikersnaam en wachtwoord, door stl2step.sh in de container gezet
GN="\033[1;92m"; YW="\033[33m"; CL="\033[m"
stap() { echo -e " ${YW}-${CL} $1..."; }
ok()   { echo -e " ${GN}✓${CL} $1"; }

[ "$(id -u)" = 0 ] || { echo "Voer dit script uit als root."; exit 1; }

stap "Pakketten installeren (FreeCAD is groot, dit duurt een paar minuten)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends freecad python3-numpy unattended-upgrades >/dev/null
FREECADCMD=$(command -v freecadcmd || command -v FreeCADCmd || true)
[ -n "$FREECADCMD" ] || { echo "freecadcmd niet gevonden na installatie."; exit 1; }
ok "FreeCAD en numpy geinstalleerd"

cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APT_EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT_EOF

stap "Gebruiker en mappen aanmaken"
id "$GEBRUIKER" >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/stl2step --shell /usr/sbin/nologin "$GEBRUIKER"
mkdir -p "$DATA/stl" "$DATA/step" "$APP"
chown -R "$GEBRUIKER:$GEBRUIKER" "$DATA"
ok "Mappen $DATA/stl en $DATA/step"

stap "Programma plaatsen"
install -m 644 "$SRC/convert.py" "$SRC/watcher.py" "$SRC/web.py" "$APP/"
rm -rf "$APP/__pycache__"

cat > /etc/systemd/system/stl2step.service <<UNIT_EOF
[Unit]
Description=STL naar STEP converter (mapbewaking)
After=network.target

[Service]
User=$GEBRUIKER
Environment=STL_DIR=$DATA/stl STEP_DIR=$DATA/step FREECADCMD=$FREECADCMD QT_QPA_PLATFORM=offscreen LANG=C.UTF-8
ExecStart=/usr/bin/python3 $APP/watcher.py
Restart=always
RestartSec=5
Nice=10

[Install]
WantedBy=multi-user.target
UNIT_EOF

cat > /etc/systemd/system/stl2step-web.service <<UNIT_EOF
[Unit]
Description=STL naar STEP webpagina
After=network.target

[Service]
User=$GEBRUIKER
Environment=STL_DIR=$DATA/stl STEP_DIR=$DATA/step PORT=$POORT LANG=C.UTF-8
ExecStart=/usr/bin/python3 $APP/web.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT_EOF

for dienst in stl2step stl2step-web; do
  mkdir -p "/etc/systemd/system/$dienst.service.d"
  cat > "/etc/systemd/system/$dienst.service.d/hardening.conf" <<'HARD_EOF'
[Service]
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/srv/cad/stl /srv/cad/step /var/lib/stl2step/
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
HARD_EOF
done

ok "Programma in $APP"

if [ "$MET_SAMBA" = "ja" ]; then
  stap "Samba-share instellen (met wachtwoord)"
  apt-get install -y -qq --no-install-recommends samba >/dev/null
  [ -f "$PWBESTAND" ] || { echo "Wachtwoordbestand $PWBESTAND ontbreekt."; exit 1; }
  { read -r SMBUSER; read -r pw; } < "$PWBESTAND"
  rm -f "$PWBESTAND"
  id "$SMBUSER" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$SMBUSER"
  # oude Samba-gebruikers weg, alleen de gekozen gebruiker blijft
  for oud in $(pdbedit -L | cut -d: -f1); do
    if [ "$oud" != "$SMBUSER" ]; then
      smbpasswd -x "$oud"
    fi
  done
  net cache flush
  printf '%s\n%s\n' "$pw" "$pw" | smbpasswd -s -a "$SMBUSER" >/dev/null
  unset pw
  CONF=/etc/samba/smb.conf
  awk '/^\[cad\]/{skip=1;next} /^\[/{skip=0} !skip' "$CONF" > "$CONF.nieuw" && mv "$CONF.nieuw" "$CONF"
  cat >> "$CONF" <<SMB_EOF
[cad]
   comment = STL naar STEP
   path = $DATA
   browseable = yes
   read only = no
   guest ok = no
   valid users = $SMBUSER
   force user = $GEBRUIKER
   create mask = 0664
   directory mask = 0775
SMB_EOF
  ok "Share 'cad' voor gebruiker $SMBUSER"
else
  systemctl disable --now smbd nmbd 2>/dev/null || true
  ok "Geen Samba-share (alleen de webpagina)"
fi

stap "Diensten starten"
DIENSTEN="stl2step stl2step-web"
if [ "$MET_SAMBA" = "ja" ]; then
  DIENSTEN="$DIENSTEN smbd"
fi
systemctl daemon-reload
systemctl enable -q $DIENSTEN
systemctl restart $DIENSTEN
sleep 2

for dienst in $DIENSTEN; do
  systemctl is-active -q "$dienst" || { echo "Dienst $dienst is niet gestart; kijk met: systemctl status $dienst"; exit 1; }
done

ok "Diensten draaien: $DIENSTEN"