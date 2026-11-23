"""Eigenes Dashboard „Heizung“ in der Seitenleiste – wird aus den Räumen erzeugt.

Home Assistant bietet Integrationen keine offizielle Schnittstelle für Dashboards.
Hier wird – wie bei anderen Integrationen – ein Lovelace-Speicher direkt registriert.
Schlägt das fehl (z. B. nach einem großen HA-Update), fehlt nur das Dashboard;
die Heizungssteuerung ist davon unabhängig.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_ROOM_CLIMATE, CONF_ROOM_ICON, CONF_ROOM_NAME, CONF_ROOM_SENSOR

_LOGGER = logging.getLogger(__name__)

URL_PATH = "heizplaner-heizung"
DASHBOARD_ID = "heizplaner_heizung"
TITLE = "Heizung"
ICON = "mdi:radiator"


def _device_entities(hass: HomeAssistant, entity_id: str | None) -> list[er.RegistryEntry]:
    if not entity_id:
        return []
    reg = er.async_get(hass)
    ent = reg.async_get(entity_id)
    if ent is None or ent.device_id is None:
        return []
    return [e for e in er.async_entries_for_device(reg, ent.device_id) if not e.disabled_by]


def _humidity_for(hass: HomeAssistant, sensor: str | None) -> str | None:
    """Luftfeuchte vom selben Gerät wie der Temperatursensor."""
    return next(
        (
            e.entity_id
            for e in _device_entities(hass, sensor)
            if e.domain == "sensor" and (e.device_class or e.original_device_class) == "humidity"
        ),
        None,
    )


def _degraded_for(hass: HomeAssistant, climate: str) -> str | None:
    """„Sensor beeinträchtigt“ des Tado X Proxy."""
    return next(
        (
            e.entity_id
            for e in _device_entities(hass, climate)
            if e.domain == "binary_sensor" and (e.translation_key == "sensor_degraded" or "degraded" in e.unique_id)
        ),
        None,
    )


def build_config(hass: HomeAssistant, rooms: list[dict[str, Any]], is_proxy) -> dict[str, Any]:
    """Dashboard-Konfiguration aus den Räumen.

    Raster mit 4 Spalten:
    Reihe 1: Heizplaner (2 Spalten) | Alle Räume – Verläufe (2 Spalten)
    darunter: ein Raum pro Spalte, alle gleich aufgebaut.
    Auf kleineren Bildschirmen bricht HA das Raster automatisch um.
    """
    room_sections: list[dict[str, Any]] = []
    temps, hums = [], []
    for room in rooms:
        name = room[CONF_ROOM_NAME]
        icon = room.get(CONF_ROOM_ICON) or "mdi:home-thermometer"
        climate = room[CONF_ROOM_CLIMATE]
        sensor = room.get(CONF_ROOM_SENSOR)
        humidity = _humidity_for(hass, sensor)
        degraded = _degraded_for(hass, climate)
        if sensor:
            temps.append({"entity": sensor, "name": name})
        if humidity:
            hums.append({"entity": humidity, "name": name})

        heading: dict[str, Any] = {"type": "heading", "heading": name, "heading_style": "title", "icon": icon}
        if degraded:
            heading["badges"] = [
                {
                    "type": "entity",
                    "entity": degraded,
                    "name": "Raumsensor gestört",
                    "show_name": True,
                    "show_state": False,
                    "color": "red",
                    "visibility": [{"condition": "state", "entity": degraded, "state": "on"}],
                }
            ]
        features: list[dict[str, Any]] = [{"type": "target-temperature"}]
        if is_proxy(climate):
            features.append(
                {"type": "climate-preset-modes", "style": "icons", "preset_modes": ["comfort", "eco", "boost", "away"]}
            )
        cards: list[dict[str, Any]] = [
            heading,
            {
                "type": "tile",
                "entity": climate,
                "name": "Heizung",
                "icon": "mdi:radiator",
                "state_content": ["preset_mode", "hvac_action"],
                "features_position": "bottom",
                "features": features,
                "grid_options": {"columns": "full"},
            },
        ]
        # Temperatur + Luftfeuchte immer als Paar nebeneinander (gleiche Höhe in allen Räumen)
        for entity, label, color in ((sensor, "Temperatur", "orange"), (humidity, "Luftfeuchte", "light-blue")):
            if entity:
                cards.append(
                    {
                        "type": "tile",
                        "entity": entity,
                        "name": label,
                        "color": color,
                        "vertical": False,
                        "features_position": "bottom",
                        "features": [{"type": "trend-graph", "hours_to_show": 24}],
                        "grid_options": {"columns": 6, "rows": 2},
                    }
                )
        room_sections.append({"type": "grid", "cards": cards})

    planer_section = {
        "type": "grid",
        "column_span": 2,
        "cards": [{"type": "custom:heizplaner-card", "title": "Heizplaner", "grid_options": {"columns": "full"}}],
    }
    sections: list[dict[str, Any]] = [planer_section]
    if temps or hums:
        cards = [{"type": "heading", "heading": "Alle Räume", "heading_style": "title", "icon": "mdi:chart-line"}]
        if temps:
            cards.append(
                {"type": "history-graph", "title": "Temperatur (24 h)", "hours_to_show": 24, "entities": temps,
                 "grid_options": {"columns": "full"}}
            )
        if hums:
            cards.append(
                {"type": "history-graph", "title": "Luftfeuchte (24 h)", "hours_to_show": 24, "entities": hums,
                 "grid_options": {"columns": "full"}}
            )
        sections.append({"type": "grid", "column_span": 2, "cards": cards})
    sections += room_sections

    return {
        "title": TITLE,
        "views": [
            {
                "title": TITLE,
                "path": "heizung",
                "icon": ICON,
                "type": "sections",
                "max_columns": 4,
                "dense_section_placement": True,
                "sections": sections,
            }
        ],
    }


def config_hash(config: dict[str, Any] | None) -> str | None:
    if config is None:
        return None
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Dashboard:
    """Registriert das Dashboard und hält es aktuell, solange es nicht von Hand geändert wurde."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = None
        self.registered = False

    def register(self) -> bool:
        try:
            from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415
            from homeassistant.components.lovelace.dashboard import LovelaceStorage  # noqa: PLC0415
        except ImportError:
            _LOGGER.warning("Dashboard: Lovelace-Schnittstelle nicht gefunden")
            return False
        data = self.hass.data.get(LOVELACE_DATA)
        if data is None:
            _LOGGER.warning("Dashboard: Lovelace ist nicht geladen")
            return False
        existing = data.dashboards.get(URL_PATH)
        if existing is not None and not getattr(existing, "_heizplaner", False):
            _LOGGER.warning("Dashboard: /%s ist schon belegt", URL_PATH)
            return False
        try:
            store = LovelaceStorage(
                self.hass,
                {
                    "id": DASHBOARD_ID,
                    "url_path": URL_PATH,
                    "title": TITLE,
                    "icon": ICON,
                    "show_in_sidebar": True,
                    "require_admin": False,
                    "mode": "storage",
                },
            )
            store._heizplaner = True  # noqa: SLF001 - Kennzeichen für unser Dashboard
            data.dashboards[URL_PATH] = store
            frontend.async_register_built_in_panel(
                self.hass,
                "lovelace",
                sidebar_title=TITLE,
                sidebar_icon=ICON,
                frontend_url_path=URL_PATH,
                config={"mode": "storage"},
                require_admin=False,
                update=existing is not None,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Dashboard konnte nicht angelegt werden")
            return False
        self._store = store
        self.registered = True
        return True

    def unregister(self) -> None:
        if not self.registered:
            return
        try:
            from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415

            frontend.async_remove_panel(self.hass, URL_PATH, warn_if_unknown=False)
            data = self.hass.data.get(LOVELACE_DATA)
            if data is not None:
                data.dashboards.pop(URL_PATH, None)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Dashboard abmelden fehlgeschlagen", exc_info=True)
        self.registered = False

    async def async_current(self) -> dict[str, Any] | None:
        if self._store is None:
            return None
        try:
            return await self._store.async_load(False)
        except Exception:  # noqa: BLE001 - ConfigNotFound = noch leer
            return None

    async def async_update(self, config: dict[str, Any], last_hash: str | None, force: bool) -> tuple[str | None, bool]:
        """Schreibt die Konfiguration, wenn erlaubt. Gibt (neuer Hash, von Hand geändert) zurück."""
        if self._store is None:
            return last_hash, False
        current = await self.async_current()
        edited = current is not None and last_hash is not None and config_hash(current) != last_hash
        if current is not None and last_hash is None:
            edited = True  # Dashboard existiert, stammt aber nicht (nachweislich) von uns
        if edited and not force:
            return last_hash, True
        new_hash = config_hash(config)
        if current is None or config_hash(current) != new_hash or force:
            await self._store.async_save(config)
        return new_hash, False


async def async_register_card_resource(hass: HomeAssistant, url: str) -> None:
    """Karte zusätzlich als Dashboard-Ressource eintragen (wie HACS-Karten).

    Damit lädt jedes Dashboard die Karte zuverlässig – auch wenn der Browser
    die von der Integration gemeldete Modul-URL nicht übernimmt.
    """
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA  # noqa: PLC0415
    except ImportError:
        return
    data = hass.data.get(LOVELACE_DATA)
    if data is None or getattr(data, "resource_mode", "storage") != "storage":
        return
    resources = data.resources
    try:
        if not getattr(resources, "loaded", True):
            await resources.async_load()
            resources.loaded = True
        base = url.split("?", 1)[0]
        ours = [r for r in resources.async_items() if str(r.get("url", "")).split("?", 1)[0] == base]
        if not ours:
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.info("Karte als Dashboard-Ressource eingetragen: %s", url)
            return
        first, *dupes = ours
        if first.get("url") != url:
            await resources.async_update_item(first["id"], {"res_type": "module", "url": url})
        for dupe in dupes:
            await resources.async_delete_item(dupe["id"])
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Karte konnte nicht als Dashboard-Ressource eingetragen werden", exc_info=True)
