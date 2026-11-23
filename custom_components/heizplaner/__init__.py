"""Heizplaner – Wochenplan für Heizkörper-Thermostate und Tado X Proxys."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import (
    CARD_URL,
    CONF_ROOM_CLIMATE,
    CONF_ROOM_ICON,
    CONF_ROOM_ID,
    CONF_ROOM_NAME,
    CONF_ROOM_SENSOR,
    CONF_ROOMS,
    DAYTYPE_LABELS,
    DAYTYPES,
    DOMAIN,
    PLAN_STUFEN,
    STUFE_COLORS,
    STUFE_ICONS,
    STUFE_LABELS,
    ALL_STUFEN,
    SWITCHES,
    VERSION,
    WEEKDAYS,
)
from .discovery import ProxyCreateError, async_build_room, used_climates
from .planer import Planer
from .schedule import PlanError

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SWITCH, Platform.NUMBER, Platform.SENSOR, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type HeizplanerConfigEntry = ConfigEntry[Planer]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Karte ausliefern, Websocket-API und Dienste registrieren."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(Path(__file__).parent / "frontend" / "heizplaner-card.js"), False)]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={VERSION}")
    websocket_api.async_register_command(hass, ws_get_config)
    websocket_api.async_register_command(hass, ws_save_plan)
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HeizplanerConfigEntry) -> bool:
    planer = Planer(hass, entry)
    await planer.async_load()
    entry.runtime_data = planer
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await planer.async_start()
    await planer.async_setup_dashboard()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HeizplanerConfigEntry) -> bool:
    await entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: HeizplanerConfigEntry) -> None:
    await entry.runtime_data.async_rooms_changed()
    await hass.config_entries.async_reload(entry.entry_id)


def _get_planer(hass: HomeAssistant) -> Planer:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("Heizplaner ist nicht eingerichtet")
    return entries[0].runtime_data


# ---------------------------------------------------------------------- Websocket
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/config"})
@callback
def ws_get_config(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Alles, was die Karte braucht."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_setup", "Heizplaner ist nicht eingerichtet")
        return
    entry = entries[0]
    planer: Planer = entry.runtime_data
    reg = er.async_get(hass)

    def eid(domain: str, key: str) -> str | None:
        return reg.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")

    connection.send_result(
        msg["id"],
        {
            "version": VERSION,
            "plan_version": planer.plan_version,
            "rooms": [
                {
                    "id": r[CONF_ROOM_ID],
                    "name": r[CONF_ROOM_NAME],
                    "icon": r.get(CONF_ROOM_ICON) or "mdi:home-thermometer",
                    "climate": r[CONF_ROOM_CLIMATE],
                    "sensor": r.get(CONF_ROOM_SENSOR),
                    "plan_entity": eid("sensor", f"room_{r[CONF_ROOM_ID]}"),
                }
                for r in planer.rooms
            ],
            "schedule": planer.schedule,
            "daytypes": [{"id": tt, "label": DAYTYPE_LABELS[tt]} for tt in DAYTYPES],
            "weekdays": {"buero": planer.buero_days, "homeoffice": planer.homeoffice_days, "all": WEEKDAYS},
            "today": planer.today.daytype if planer.today else None,
            "stufen": [
                {
                    "id": s,
                    "label": STUFE_LABELS[s],
                    "color": STUFE_COLORS[s],
                    "icon": STUFE_ICONS[s],
                    "plan": s in PLAN_STUFEN,
                    "entity": eid("number", f"stufe_{s}"),
                }
                for s in ALL_STUFEN
            ],
            "switches": [
                {"id": k, "label": v[0], "icon": v[1], "entity": eid("switch", f"switch_{k}")}
                for k, v in SWITCHES.items()
            ],
            "mode_entity": eid("sensor", "modus"),
            "apply_entity": eid("button", "apply_now"),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/save_plan",
        vol.Required("room_id"): str,
        vol.Required("daytype"): vol.In(DAYTYPES),
        vol.Required("points"): list,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_plan(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        planer = _get_planer(hass)
        await planer.async_set_room_plan(msg["room_id"], msg["daytype"], msg["points"])
    except (PlanError, ValueError, ServiceValidationError) as err:
        connection.send_error(msg["id"], "invalid_plan", str(err))
        return
    connection.send_result(msg["id"], {"plan_version": planer.plan_version})


# ---------------------------------------------------------------------- Dienste
SET_PLAN_SCHEMA = vol.Schema(
    {
        vol.Required("room"): cv.string,
        vol.Required("daytype"): vol.In(DAYTYPES),
        vol.Required("points"): list,
    }
)
ADD_ROOM_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("climate_entity"): cv.entity_id,
        vol.Optional("sensor_entity"): cv.entity_id,
        vol.Optional("icon"): cv.icon,
        vol.Optional("area"): cv.string,
        vol.Optional("create_proxy", default=True): cv.boolean,
    }
)


def _register_services(hass: HomeAssistant) -> None:
    async def set_plan(call: ServiceCall) -> None:
        planer = _get_planer(hass)
        room = call.data["room"]
        rid = next(
            (r[CONF_ROOM_ID] for r in planer.rooms if room in (r[CONF_ROOM_ID], r[CONF_ROOM_NAME])),
            None,
        )
        if rid is None:
            raise ServiceValidationError(f"Raum {room!r} gibt es nicht")
        try:
            await planer.async_set_room_plan(rid, call.data["daytype"], call.data["points"])
        except PlanError as err:
            raise ServiceValidationError(str(err)) from err

    async def add_room(call: ServiceCall) -> None:
        planer = _get_planer(hass)
        rooms = planer.rooms
        climate = call.data["climate_entity"]
        if climate in used_climates(hass, rooms):
            raise ServiceValidationError("Dieses Thermostat ist schon einem Raum zugeordnet")
        try:
            room = await async_build_room(
                hass,
                {r[CONF_ROOM_ID] for r in rooms},
                name=call.data["name"],
                climate=climate,
                sensor=call.data.get("sensor_entity"),
                area_id=call.data.get("area"),
                icon=call.data.get("icon"),
                create_proxy=call.data.get("create_proxy", True),
            )
        except ProxyCreateError as err:
            raise ServiceValidationError(f"Tado X Proxy konnte nicht angelegt werden ({err.args[0]})") from err
        hass.config_entries.async_update_entry(planer.entry, options={**planer.entry.options, CONF_ROOMS: [*rooms, room]})

    async def apply_now(call: ServiceCall) -> None:
        await _get_planer(hass).async_apply_now()

    hass.services.async_register(DOMAIN, "set_plan", set_plan, SET_PLAN_SCHEMA)
    hass.services.async_register(DOMAIN, "add_room", add_room, ADD_ROOM_SCHEMA)
    hass.services.async_register(DOMAIN, "apply_now", apply_now)
