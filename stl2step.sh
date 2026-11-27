#!/usr/bin/env bash
# STL2STEP - Proxmox VE helper-script (in de stijl van de community-scripts)
#
# Uitvoeren in de shell van de Proxmox-node (niet in een container):
#     bash -c "$(curl -fsSL https://raw.githubusercontent.com/Martijn5/Stl2Step/main/stl2step.sh)"
#     bash -c "$(curl -fsSL https://raw.githubusercontent.com/Martijn5/Stl2Step/main/stl2step.sh)" _ update 105
# of vanuit een kloon van de repo:
#     bash stl2step.sh              nieuwe LXC aanmaken en STL2STEP installeren
#     bash stl2step.sh update 105   STL2STEP in bestaande container 105 bijwerken
#
# Maakt een Debian 12 LXC met:
#   - Samba-share "cad" met eigen gebruiker, mappen stl/ en step/
#   - dienst die elke STL in stl/ omzet naar step/<naam>.step (FreeCAD, zonder scherm)
#   - webpagina op poort 8080 (uploaden, status, 3D-preview, downloaden)
# De webpagina heeft geen wachtwoord; de firewall laat alleen je eigen lan toe.

set -Eeuo pipefail

APP="STL2STEP"
REPO="${STL2STEP_REPO:-Martijn5/Stl2Step}"
BRANCH="${STL2STEP_BRANCH:-main}"
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; else HIER=/nonexistent; fi   # leeg bij curl | bash -c
var_ctid=""
var_hostname="stl2step"
var_disk="8"        # GB
var_cpu="2"
var_ram="2048"      # MB
var_bridge="vmbr0"
var_ip="dhcp"       # of bijv. 192.168.25.40/24
var_gw=""
var_unprivileged="1"
var_lan=""          # LAN-subnet dat bij webpagina en share mag, bijv. 192.168.1.0/24
var_samba="nee"     # ja = Windows-share met wachtwoord
var_smbuser="cad"   # gebruikersnaam voor de share
var_smbpw=""
POORT=8080

YW="\033[33m"; BL="\033[36m"; RD="\033[01;31m"; GN="\033[1;92m"; DGN="\033[32m"; CL="\033[m"; BFR="\\r\\033[K"; HOLD=" "
CM="${GN}✓${CL}"; CROSS="${RD}✗${CL}"
msg_info()  { echo -ne " ${HOLD} ${YW}$1...${CL}"; }
msg_ok()    { echo -e "${BFR} ${CM} ${GN}$1${CL}"; }
msg_error() { echo -e "${BFR} ${CROSS} ${RD}$1${CL}" >&2; }
msg_warning() { echo -e "${BFR} ${YW}!${CL} ${YW}$1${CL}" >&2; }
afbreken()  { echo -e "\n ${CROSS} ${RD}Afgebroken, er is niets gewijzigd.${CL}"; exit 1; }
trap 'msg_error "Fout op regel $LINENO (commando: $BASH_COMMAND)"' ERR

header_info() {
  clear 2>/dev/null || true
  cat <<"EOF"
   _____________       ___   _____________________
  / ___/_  __/ /      |__ \ / ___/_  __/ ____/ __ \
  \__ \ / / / /       __/ / \__ \ / / / __/ / /_/ /
 ___/ // / / /___    / __/ ___/ // / / /___/ ____/
/____//_/ /_____/   /____//____//_/ /_____/_/

        STL naar STEP converter - LXC voor Proxmox VE
EOF
  echo
}

controleer_host() {
  [ "$(id -u)" = 0 ] || { msg_error "Voer dit script uit als root."; exit 1; }
  command -v pct >/dev/null && command -v pveam >/dev/null && command -v pvesm >/dev/null || {
    msg_error "Dit script moet in de shell van de Proxmox-node draaien (pct/pveam niet gevonden)."; exit 1; }
  command -v curl >/dev/null || { msg_error "curl ontbreekt (apt install curl)."; exit 1; }
  command -v whiptail >/dev/null || { msg_error "whiptail ontbreekt (apt install whiptail)."; exit 1; }
}

vraag() {  # vraag "Titel" "Tekst" "standaardwaarde"
  whiptail --backtitle "Proxmox VE Helper Script - $APP" --title "$1" --inputbox "$2" 9 62 "$3" 3>&1 1>&2 2>&3 || afbreken
}

vraag_samba() {  # vult var_samba, var_smbuser en var_smbpw; Nee = geen share
  whiptail --backtitle "Proxmox VE Helper Script - $APP" --title "SAMBA" --yesno \
    "Windows-share (Samba) installeren?\n\nZonder share werk je alleen via de webpagina." 10 62 || return 0
  var_samba="ja"
  var_smbuser=$(vraag "SAMBA" "Gebruikersnaam voor de share:" "$var_smbuser")
  [[ "$var_smbuser" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || { msg_error "Ongeldige gebruikersnaam: $var_smbuser"; exit 1; }
  local pw2
  while true; do
    var_smbpw=$(whiptail --backtitle "Proxmox VE Helper Script - $APP" --title "SAMBA" --passwordbox "Wachtwoord voor $var_smbuser (minstens 12 tekens):" 9 62 3>&1 1>&2 2>&3) || afbreken
    pw2=$(whiptail --backtitle "Proxmox VE Helper Script - $APP" --title "SAMBA" --passwordbox "Herhaal het wachtwoord:" 9 62 3>&1 1>&2 2>&3) || afbreken
    if [ "$var_smbpw" != "$pw2" ]; then
      whiptail --backtitle "Proxmox VE Helper Script - $APP" --title "SAMBA" --msgbox "De wachtwoorden zijn niet gelijk. Probeer opnieuw." 8 62
    elif [ ${#var_smbpw} -lt 12 ]; then
      whiptail --backtitle "Proxmox VE Helper Script - $APP" --title "SAMBA" --msgbox "Te kort: minstens 12 tekens." 8 62
    else
      break
    fi
  done
}

kies_opslag() {  # kies_opslag <inhoudstype> <omschrijving>
  local lijst=() menu=() s eerste=ON
  mapfile -t lijst < <(pvesm status -content "$1" 2>/dev/null | awk 'NR>1{print $1}')
  [ "${#lijst[@]}" -gt 0 ] || { msg_error "Geen opslag gevonden voor $2."; return 1; }
  if [ "${#lijst[@]}" -eq 1 ]; then echo "${lijst[0]}"; return 0; fi
  for s in "${lijst[@]}"; do menu+=("$s" "" "$eerste"); eerste=OFF; done
  whiptail --backtitle "Proxmox VE Helper Script - $APP" --title "Opslag" --radiolist \
    "Welke opslag voor $2?\n(spatie = kiezen, enter = bevestigen)" 16 62 6 "${menu[@]}" 3>&1 1>&2 2>&3
}

instellingen() {
  var_ctid=$(pvesh get /cluster/nextid)
  var_lan=$(pve-firewall localnet | awk '/using detected/ {print $NF}')
  local keuze
  keuze=$(whiptail --backtitle "Proxmox VE Helper Script - $APP" --title "INSTELLINGEN" --menu "Kies een optie:" 12 62 2 \
    "1" "Standaardinstellingen" \
    "2" "Geavanceerd (ID, naam, grootte, vast IP)" 3>&1 1>&2 2>&3) || afbreken
  if [ "$keuze" = "2" ]; then
    var_ctid=$(vraag "CONTAINER-ID" "Container-ID:" "$var_ctid")
    var_hostname=$(vraag "HOSTNAAM" "Hostnaam:" "$var_hostname")
    var_disk=$(vraag "SCHIJF" "Schijfgrootte in GB (FreeCAD heeft zo'n 3 GB nodig):" "$var_disk")
    var_cpu=$(vraag "CPU" "Aantal cores:" "$var_cpu")
    var_ram=$(vraag "GEHEUGEN" "RAM in MB (grote STL's vragen meer):" "$var_ram")
    var_bridge=$(vraag "NETWERK" "Bridge:" "$var_bridge")
    var_ip=$(vraag "IP-ADRES" "IPv4-adres met masker (bijv. 192.168.1.40/24) of 'dhcp':" "$var_ip")
    if [ "$var_ip" != "dhcp" ]; then
      [[ "$var_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]] || { msg_error "Ongeldig IP-adres: $var_ip (verwacht bijv. 192.168.1.40/24)"; exit 1; }
      var_gw=$(vraag "GATEWAY" "Gateway (adres van je router):" "${var_ip%.*}.1")
    fi
    var_lan=$(vraag "LAN" "Welk netwerk mag bij webpagina en share (bijv. 192.168.1.0/24):" "$var_lan")
  fi
  [[ "$var_ctid" =~ ^[0-9]+$ ]] || { msg_error "Ongeldige container-ID: $var_ctid"; exit 1; }
  [[ "$var_lan" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]] || { msg_error "Ongeldig LAN-subnet: '$var_lan' (verwacht bijv. 192.168.1.0/24)"; exit 1; }
  if pct status "$var_ctid" >/dev/null 2>&1 || qm status "$var_ctid" >/dev/null 2>&1; then
    msg_error "ID $var_ctid is al in gebruik."; exit 1
  fi
  echo -e " ${DGN}Container-ID:   ${BL}$var_ctid${CL}"
  echo -e " ${DGN}Hostnaam:       ${BL}$var_hostname${CL}"
  echo -e " ${DGN}Besturingssyst: ${BL}Debian 12 (unprivileged)${CL}"
  echo -e " ${DGN}Schijf:         ${BL}${var_disk} GB${CL}"
  echo -e " ${DGN}Cores / RAM:    ${BL}${var_cpu} / ${var_ram} MB${CL}"
  echo -e " ${DGN}Netwerk:        ${BL}${var_bridge}, ${var_ip}${var_gw:+ (gateway $var_gw)}${CL}"
  echo
}

installeer_in_ct() {  # installeer_in_ct <ctid>: code ophalen, in de container zetten en installeren
  local werk
  werk=$(mktemp -d)
  if [ -f "$HIER/install/install.sh" ] && [ -f "$HIER/src/convert.py" ]; then
    msg_info "Code uit lokale map gebruiken ($HIER)"
    tar -czf "$werk/stl2step.tar.gz" --exclude=__pycache__ -C "$HIER" install src
  else
    msg_info "Code downloaden van GitHub ($REPO, branch $BRANCH)"
    curl -fsSL "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz" -o "$werk/bron.tar.gz"
    mkdir "$werk/bron" && tar -xzf "$werk/bron.tar.gz" -C "$werk/bron" --strip-components=1
    tar -czf "$werk/stl2step.tar.gz" -C "$werk/bron" install src
  fi
  pct push "$1" "$werk/stl2step.tar.gz" /root/stl2step.tar.gz >/dev/null
  rm -rf "$werk"
  msg_ok "Code klaargezet in container $1"

  if [ "$var_samba" = "ja" ]; then
    local pwbestand
    pwbestand=$(mktemp)
    chmod 600 "$pwbestand"
    printf '%s\n%s\n' "$var_smbuser" "$var_smbpw" > "$pwbestand"
    pct push "$1" "$pwbestand" /root/.stl2step-smbpw --perms 600
    rm -f "$pwbestand"
  fi

  pct exec "$1" -- env MET_SAMBA="$var_samba" bash -c 'rm -rf /root/stl2step-bron && mkdir /root/stl2step-bron && tar -xzf /root/stl2step.tar.gz -C /root/stl2step-bron && rm /root/stl2step.tar.gz && bash /root/stl2step-bron/install/install.sh'
}

ct_ip() { pct exec "$1" -- hostname -I 2>/dev/null | awk '{print $1}'; }

klaar_melding() {
  local ip
  ip=$(ct_ip "$1")
  echo
  msg_ok "Voltooid!"
  echo -e " ${APP} is bereikbaar op:"
  echo -e "   ${BL}Webpagina:${CL}  http://${ip:-<ip-van-container>}:${POORT}"
  if [ "$var_samba" = "ja" ]; then
    echo -e "   ${BL}Share:${CL}      \\\\\\\\${ip:-<ip-van-container>}\\\\cad   (met wachtwoord; mappen stl en step)"
  fi
  echo -e " Console van de container:  pct enter $1"
  echo -e " Later bijwerken:           bash stl2step.sh update $1   (of de curl-regel, met  _ update $1  erachter)"
}

# ---------------------------------------------------------------- update
if [ "${1:-}" = "update" ]; then
  header_info
  controleer_host
  ctid="${2:-}"
  [[ "$ctid" =~ ^[0-9]+$ ]] || { msg_error "Gebruik: bash stl2step.sh update <container-ID>"; exit 1; }
  pct status "$ctid" 2>/dev/null | grep -q running || { msg_error "Container $ctid bestaat niet of draait niet."; exit 1; }
  vraag_samba
  echo -e " ${YW}STL2STEP bijwerken in container $ctid${CL}"
  installeer_in_ct "$ctid"
  klaar_melding "$ctid"

  exit 0
fi

# ---------------------------------------------------------------- nieuwe container
header_info
controleer_host
whiptail --backtitle "Proxmox VE Helper Script - $APP" --title "$APP LXC" --yesno \
  "Dit maakt een nieuwe $APP LXC-container aan. Doorgaan?" 9 62 || afbreken
instellingen
vraag_samba

TSTORE=$(kies_opslag vztmpl "het template") || exit 1
CSTORE=$(kies_opslag rootdir "de container") || exit 1
msg_ok "Opslag: template op ${BL}$TSTORE${GN}, container op ${BL}$CSTORE"

msg_info "Lijst met templates bijwerken"
pveam update >/dev/null
TEMPLATE=$(pveam available -section system | awk '{print $2}' | grep -E '^debian-12-standard' | sort -V | tail -n1)
[ -n "$TEMPLATE" ] || { msg_error "Geen Debian 12-template gevonden."; exit 1; }
msg_ok "Template: $TEMPLATE"

if ! pveam list "$TSTORE" | grep -q "$TEMPLATE"; then
  msg_info "Template downloaden"
  pveam download "$TSTORE" "$TEMPLATE" >/dev/null
  msg_ok "Template gedownload"
fi

msg_info "LXC-container aanmaken"
NET="name=eth0,bridge=$var_bridge,ip=$var_ip,firewall=1"
[ -n "$var_gw" ] && NET="$NET,gw=$var_gw"
pct create "$var_ctid" "$TSTORE:vztmpl/$TEMPLATE" \
  --hostname "$var_hostname" --cores "$var_cpu" --memory "$var_ram" --swap 512 \
  --rootfs "$CSTORE:$var_disk" --net0 "$NET" \
  --unprivileged "$var_unprivileged" --features nesting=1 --onboot 1 --ostype debian \
  --tags "stl2step" \
  --description "STL2STEP - STL naar STEP converter. Webpagina op poort $POORT." >/dev/null
msg_ok "LXC-container $var_ctid aangemaakt"

msg_info "Firewall instellen"
smb_regel=""
if [ "$var_samba" = "ja" ]; then
  smb_regel="IN ACCEPT -source $var_lan -p tcp -dport 445 -log nolog # samba"
fi

cat > "/etc/pve/firewall/${var_ctid}.fw" <<FW_EOF
[OPTIONS]
enable: 1

[RULES]
IN ACCEPT -source $var_lan -p tcp -dport $POORT -log nolog # webpagina
$smb_regel
FW_EOF
msg_ok "Firewall ingesteld voor $var_lan"
pve-firewall status | grep -q 'enabled/running' || msg_warning "Datacenter-firewall staat uit: zet hem aan via Datacenter > Firewall > Options > Firewall: Yes"

msg_info "Container starten"
pct start "$var_ctid"
msg_ok "Container gestart"
msg_info "Wachten op netwerk"
if ! pct exec "$var_ctid" -- bash -c 'for i in $(seq 1 45); do getent hosts deb.debian.org >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1'; then
  msg_error "De container heeft geen internetverbinding (controleer bridge, IP en gateway)."
  echo -e " De container $var_ctid blijft bestaan. Na herstel: bash stl2step.sh update $var_ctid"
  exit 1
fi
msg_ok "Netwerk bereikbaar (IP: $(ct_ip "$var_ctid"))"

echo -e " ${YW}$APP installeren in de container${CL}"
installeer_in_ct "$var_ctid"
klaar_melding "$var_ctid"
