# Melding in Home Assistant

STL2STEP kan na elke conversie een bericht sturen via MQTT. Home Assistant maakt daar
automatisch een sensor van, en met de automation hieronder krijg je een melding op je telefoon.

## 1. Wat je nodig hebt

- Een MQTT-broker (bijv. Mosquitto) die Home Assistant al gebruikt.
- Een eigen MQTT-gebruiker voor STL2STEP die alleen zijn eigen topics mag schrijven.
  Voorbeeld voor het ACL-bestand van Mosquitto:
  ```
  user stl2step
  topic write stl2step/#
  topic write homeassistant/sensor/stl2step/#
  ```
- Bij de installatie (`bash stl2step.sh` of `bash stl2step.sh update <id>`) kies je **Ja** bij
  "Melding via MQTT" en vul je broker, gebruiker en wachtwoord in.

## 2. De sensor

Na het starten van de dienst verschijnt in Home Assistant vanzelf `sensor.stl2step`
(via MQTT discovery). Status: `bezig`, `klaar` of `mislukt`, met als attributen:

| attribuut | voorbeeld |
|---|---|
| `bestand` | `blok.stl` |
| `tekst` | `12 s`, of de foutmelding |
| `tijd` | `2026-11-27T12:00:00` |

Topic: `stl2step/status` (JSON, retained).

## 3. De automation

Instellingen > Automatiseringen en scènes > **+ Automatisering maken** > Nieuwe automatisering >
menu (drie puntjes) rechtsboven > **Bewerken in YAML**, en plak dit erin.

Pas twee dingen aan:
- `notify.mobile_app_JOUW_TELEFOON`: je eigen telefoon. Zoek hem op via
  Ontwikkelhulpmiddelen > Acties, typ `notify.mobile_app`.
- `webpagina`: het adres van je STL2STEP-container.

```yaml
alias: STL2STEP melding
description: Eén melding per conversie die meegaat van bezig naar klaar of mislukt
mode: queued
triggers:
  - trigger: state
    entity_id: sensor.stl2step
conditions:
  # niet melden bij het opstarten van HA of als de sensor even weg is
  - condition: template
    value_template: >-
      {{ trigger.from_state is not none
         and trigger.from_state.state not in ['unknown', 'unavailable']
         and trigger.to_state.state in ['bezig', 'klaar', 'mislukt'] }}
actions:
  - variables:
      status: "{{ trigger.to_state.state }}"
      bestand: "{{ trigger.to_state.attributes.bestand }}"
      tekst: "{{ trigger.to_state.attributes.tekst }}"
      icoon: "{{ {'bezig': '⏳', 'klaar': '✅', 'mislukt': '❌'}[status] }}"
      webpagina: "http://IP-VAN-JE-CONTAINER:8080"
  - action: notify.mobile_app_JOUW_TELEFOON
    data:
      title: "{{ icoon }} STL2STEP {{ status }}"
      message: >-
        {% if status == 'bezig' %}{{ bestand }} wordt omgezet naar STEP…
        {% elif status == 'klaar' %}{{ bestand }} is klaar ({{ tekst }})
        {% else %}{{ bestand }}: {{ tekst }}{% endif %}
      data:
        tag: stl2step                      # zelfde tag = deze melding vervangt de vorige
        group: stl2step                    # meldingen van STL2STEP bij elkaar
        subtitle: "{{ bestand }}"          # iPhone: tweede regel onder de titel
        url: "{{ webpagina }}"             # iPhone: tikken opent de webpagina
        clickAction: "{{ webpagina }}"     # Android: tikken opent de webpagina
        notification_icon: mdi:printer-3d  # Android: eigen icoon (iPhone toont altijd het HA-icoon)
        color: "{{ {'bezig': '#2196F3', 'klaar': '#4CAF50', 'mislukt': '#F44336'}[status] }}"   # Android
        push:
          sound: "{{ 'none' if status == 'bezig' else 'default' }}"     # bezig: stil
          interruption-level: "{{ {'bezig': 'passive', 'klaar': 'active', 'mislukt': 'time-sensitive'}[status] }}"
```

## Wat je krijgt

- ⏳ **bezig**: stil, zonder geluid.
- ✅ **klaar**: vervangt de bezig-melding, met geluid.
- ❌ **mislukt**: als *tijdgevoelig*, zodat hij ook door een focusmodus heen komt.
- Tikken op de melding opent de webpagina.

Alleen bij fouten een melding? Zet in de voorwaarde `['mislukt']` in plaats van
`['bezig', 'klaar', 'mislukt']`.