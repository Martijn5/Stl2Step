#!/bin/bash
# STL2STEP - installatie BINNEN de container (Debian 12/13), als root.
# Wordt door stl2step.sh aangeroepen, maar kan ook los vanuit een kloon van de repo:
#     bash install/install.sh
# Opnieuw uitvoeren = bijwerken.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../src" && pwd)"
[ -f "$SRC/convert.py" ] || { echo "Bronbestanden niet gevonden in $SRC"; exit 1; }
GEBRUIKER=cad
DATA=/srv/cad
APP=/opt/stl2step
POORT=8080
GN="\033[1;92m"; YW="\033[33m"; CL="\033[m"
stap() { echo -e " ${YW}-${CL} $1..."; }
ok()   { echo -e " ${GN}✓${CL} $1"; }

[ "$(id -u)" = 0 ] || { echo "Voer dit script uit als root."; exit 1; }

stap "Pakketten installeren (FreeCAD is groot, dit duurt een paar minuten)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends freecad python3-numpy samba >/dev/null
FREECADCMD=$(command -v freecadcmd || command -v FreeCADCmd || true)
[ -n "$FREECADCMD" ] || { echo "freecadcmd niet gevonden na installatie."; exit 1; }
ok "FreeCAD, numpy en Samba geinstalleerd"

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
ok "Programma in $APP"

stap "Samba-share instellen (zonder wachtwoord)"
CONF=/etc/samba/smb.conf
awk '/^\[cad\]/{skip=1;next} /^\[/{skip=0} !skip' "$CONF" > "$CONF.nieuw" && mv "$CONF.nieuw" "$CONF"
grep -qi '^[[:space:]]*map to guest' "$CONF" || sed -i '0,/^\[global\]/s//[global]\n   map to guest = Bad User/' "$CONF"
cat >> "$CONF" <<SMB_EOF
[cad]
   comment = STL naar STEP
   path = $DATA
   browseable = yes
   read only = no
   guest ok = yes
   guest only = yes
   force user = $GEBRUIKER
   create mask = 0664
   directory mask = 0775
SMB_EOF
ok "Share 'cad'"

stap "Diensten starten"
systemctl daemon-reload
systemctl enable -q stl2step.service stl2step-web.service
systemctl restart stl2step.service stl2step-web.service smbd
sleep 2
systemctl is-active -q stl2step.service stl2step-web.service smbd || { echo "Een dienst is niet gestart; kijk met: systemctl status stl2step stl2step-web smbd"; exit 1; }
ok "Diensten stl2step, stl2step-web en smbd draaien"
