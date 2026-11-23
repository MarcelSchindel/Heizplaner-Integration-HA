# Heizplaner für Home Assistant

Wochenplan für die Heizung, gebaut für den [Tado X Proxy](https://github.com/kinimodb/ha-tadox-proxy) –
funktioniert aber auch mit normalen Thermostaten (`climate`-Entitäten).

## Funktionen
- **Automatische Erkennung** beim Einrichten und über *Konfigurieren → Räume suchen*:
  vorhandene Tado X Proxys (Name aus dem Bereich, Sensor aus den Proxy-Einstellungen),
  Tado-Thermostate ohne Proxy und andere Thermostate. Thermostate hinter einem Proxy erscheinen nicht doppelt.
- **Tado X Proxy direkt anlegen**: Für ein Tado-Thermostat ohne Proxy legt der Heizplaner über den
  Einrichtungsdialog des Proxys einen an – mit dem Temperatursensor aus dem Bereich – und ordnet ihn dem Bereich zu.
- **Neuer Proxy gefunden**: Wird später ein Proxy angelegt, erscheint unter *Einstellungen → Reparaturen*
  ein Hinweis, mit dem man ihn per Klick als Raum übernimmt.
- **Tagtypen** Bürotag / Homeoffice / Wochenende, Wochentage frei wählbar
- **Feiertage** des Bundeslands werden automatisch wie ein Wochenende behandelt
- **Schalter**: Heizplan · Homeoffice heute (setzt sich um Mitternacht zurück) · Frei / zu Hause · Verreist
- **Stufen** Komfort, Eco, Nacht, Schlafen, Verreist – bleiben über Neustarts erhalten
- **Tado X Proxy**: Komfort/Eco/Verreist werden als Preset gesetzt und die Preset-Temperaturen
  des Proxys automatisch angeglichen; Nacht/Schlafen werden als Temperatur gesetzt.
  Normale Thermostate bekommen immer die Temperatur.
- Gesendet wird **nur an Wechselpunkten** – manuelle Änderungen bleiben bis zum nächsten Wechsel
  (Karte zeigt „Manuell bis …“). Ein laufender **Boost** wird nicht unterbrochen.
- Vor dem ersten Wechsel des Tages gilt die letzte Stufe vom Vortag.
- **Karte** `custom:heizplaner-card` mit Wochenplan-Editor – wird von der Integration automatisch geladen.

## Installation
**HACS:** HACS → ⋮ → Benutzerdefinierte Repositories → diese URL, Typ *Integration* → Heizplaner installieren.

**Manuell:** `custom_components/heizplaner` nach `/config/custom_components/` kopieren.

Danach Home Assistant neu starten und unter *Einstellungen → Geräte & Dienste → Integration hinzufügen*
**Heizplaner** einrichten. Im zweiten Schritt schlägt der Heizplaner die gefundenen Räume vor –
abhaken, fertig. Weitere Räume später über *Konfigurieren → Räume suchen* oder *Raum hinzufügen*.

> Tipp: Thermostaten und Temperatursensoren einen **Bereich** geben – dann passen Raumnamen und
> Sensor-Vorschläge automatisch.

Das Anlegen von Proxys nutzt den Einrichtungsdialog von [ha-tadox-proxy](https://github.com/kinimodb/ha-tadox-proxy)
(getestet mit 1.6.1). Ändert sich dieser Dialog, meldet der Heizplaner das – der Proxy kann dann
von Hand angelegt und hier ausgewählt werden.

## Karte
```yaml
type: custom:heizplaner-card
title: Heizplaner        # optional
rooms: [wohnzimmer, buero]  # optional: nur diese Räume
```
- Tab wählen (Bürotag / Homeoffice / Wochenende), ✏️ am Raum öffnet den Editor
- Klick auf die Zeitleiste fügt dort einen Wechsel ein
- „Auch übernehmen für“ kopiert den Plan auf andere Tagtypen oder Räume

Ein komplettes Beispiel-Dashboard liegt in [`examples/`](examples/).

## Entitäten
| Entität | Zweck |
|---|---|
| `switch.heizplaner_heizplan` | Plan an/aus |
| `switch.heizplaner_homeoffice_heute` | heute Homeoffice statt Bürotag |
| `switch.heizplaner_frei_zu_hause` | Werktag wie Wochenende (bleibt an, bis man ihn ausschaltet) |
| `switch.heizplaner_verreist` | alle Räume auf Verreist |
| `number.heizplaner_<stufe>` | Temperatur je Stufe |
| `sensor.heizplaner_modus` | was heute gilt |
| `sensor.heizplaner_<raum>` | Plan-Status je Raum (Attribute: stufe, ziel, naechster_wechsel, manuell …) |
| `button.heizplaner_plan_jetzt_anwenden` | Plan sofort senden (überschreibt manuelle Änderungen) |

## Dienste
- `heizplaner.set_plan` – `room`, `daytype` (`buero`/`homeoffice`/`wochenende`), `points` z. B. `[["06:00","komfort"],["22:30","nacht"]]`
- `heizplaner.add_room` – `name`, `climate_entity`, optional `sensor_entity`, `icon`, `area`,
  `create_proxy` (Standard: an – legt bei einem Tado-Thermostat ohne Proxy einen an)
- `heizplaner.apply_now`

## Tests
```bash
pip install pytest && pytest tests
```
