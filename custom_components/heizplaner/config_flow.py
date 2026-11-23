"""Einrichtung und Optionen: Räume finden/anlegen (inkl. Tado X Proxy), Tage, Bundesland."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_BUERO_DAYS,
    CONF_CREATE_PROXY,
    CONF_DASHBOARD,
    CONF_HOMEOFFICE_DAYS,
    CONF_ROOM_AREA,
    CONF_ROOM_CLIMATE,
    CONF_ROOM_ICON,
    CONF_ROOM_ID,
    CONF_ROOM_NAME,
    CONF_ROOM_SENSOR,
    CONF_ROOMS,
    CONF_SELECTED,
    CONF_SUBDIV,
    DEFAULT_BUERO_DAYS,
    DEFAULT_HOMEOFFICE_DAYS,
    DEFAULT_SUBDIV,
    DOMAIN,
    SUBDIVISIONS,
    WEEKDAY_LABELS,
    WEEKDAYS,
)
from .discovery import (
    KIND_PROXY,
    KIND_TADO,
    Candidate,
    ProxyCreateError,
    _area_name,
    _area_of,
    _clean_name,
    _friendly,
    async_build_room,
    find_candidates,
    is_tado_trv,
    proxy_for,
    suggest_sensor,
)


def _days_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=d, label=WEEKDAY_LABELS[d]) for d in WEEKDAYS],
            multiple=True,
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _settings_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SUBDIV, default=defaults.get(CONF_SUBDIV, DEFAULT_SUBDIV)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[selector.SelectOptionDict(value=k, label=v) for k, v in SUBDIVISIONS.items()],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_BUERO_DAYS, default=defaults.get(CONF_BUERO_DAYS, DEFAULT_BUERO_DAYS)): _days_selector(),
            vol.Required(
                CONF_HOMEOFFICE_DAYS, default=defaults.get(CONF_HOMEOFFICE_DAYS, DEFAULT_HOMEOFFICE_DAYS)
            ): _days_selector(),
            vol.Required(CONF_DASHBOARD, default=defaults.get(CONF_DASHBOARD, True)): selector.BooleanSelector(),
        }
    )


def _check_days(user_input: dict[str, Any]) -> dict[str, str]:
    if set(user_input[CONF_BUERO_DAYS]) & set(user_input[CONF_HOMEOFFICE_DAYS]):
        return {"base": "days_overlap"}
    return {}


def _suggested(value: Any) -> dict[str, Any] | None:
    return {"suggested_value": value} if value not in (None, "") else None


def _candidates_schema(candidates: list[Candidate]) -> vol.Schema:
    preselect = [c.key for c in candidates if c.kind == KIND_PROXY or (c.kind == KIND_TADO and c.sensor)]
    return vol.Schema(
        {
            vol.Optional(CONF_SELECTED, default=preselect): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[selector.SelectOptionDict(value=c.key, label=c.label()) for c in candidates],
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
    )


async def _rooms_from_candidates(
    hass: HomeAssistant, candidates: list[Candidate], selected: list[str], rooms: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Ausgewählte Vorschläge zu Räumen machen. Gibt (neue Räume, Fehlertexte) zurück."""
    ids = {r[CONF_ROOM_ID] for r in rooms}
    new: list[dict[str, Any]] = []
    failed: list[str] = []
    for cand in candidates:
        if cand.key not in selected:
            continue
        try:
            room = await async_build_room(
                hass,
                ids,
                name=cand.name,
                climate=cand.climate,
                sensor=cand.sensor,
                area_id=cand.area_id,
                icon=cand.icon,
                create_proxy=cand.kind == KIND_TADO and bool(cand.sensor),
            )
        except ProxyCreateError as err:
            failed.append(f"{cand.name}: {err.args[0]}")
            continue
        ids.add(room[CONF_ROOM_ID])
        new.append(room)
    return new, failed


class HeizplanerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einrichtung: Einstellungen, dann gefundene Räume übernehmen."""

    VERSION = 1

    def __init__(self) -> None:
        self._settings: dict[str, Any] = {}
        self._candidates: list[Candidate] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_days(user_input)
            if not errors:
                self._settings = user_input
                self._candidates = find_candidates(self.hass, [])
                if not self._candidates:
                    return self.async_create_entry(title="Heizplaner", data={}, options={**user_input, CONF_ROOMS: []})
                return await self.async_step_rooms()
        return self.async_show_form(step_id="user", data_schema=_settings_schema(user_input or {}), errors=errors)

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            rooms, failed = await _rooms_from_candidates(
                self.hass, self._candidates, user_input.get(CONF_SELECTED, []), []
            )
            if failed and not rooms:
                return self.async_show_form(
                    step_id="rooms",
                    data_schema=_candidates_schema(self._candidates),
                    errors={"base": "proxy_failed"},
                    description_placeholders={"failed": ", ".join(failed)},
                )
            return self.async_create_entry(title="Heizplaner", data={}, options={**self._settings, CONF_ROOMS: rooms})
        return self.async_show_form(
            step_id="rooms",
            data_schema=_candidates_schema(self._candidates),
            description_placeholders={"failed": ""},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HeizplanerOptionsFlow()


class HeizplanerOptionsFlow(OptionsFlow):
    """Räume verwalten und Einstellungen ändern."""

    def __init__(self) -> None:
        self._room_id: str | None = None
        self._candidates: list[Candidate] = []

    @property
    def _rooms(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.config_entry.options.get(CONF_ROOMS, [])]

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["scan", "add_room"]
        if self._rooms:
            menu += ["edit_room", "remove_room"]
        menu.append("settings")
        return self.async_show_menu(step_id="init", menu_options=menu)

    # --- Räume suchen
    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            self._candidates = find_candidates(self.hass, self._rooms)
            if not self._candidates:
                return self.async_abort(reason="nothing_found")
            return self.async_show_form(
                step_id="scan", data_schema=_candidates_schema(self._candidates), description_placeholders={"failed": ""}
            )
        rooms = self._rooms
        new, failed = await _rooms_from_candidates(
            self.hass, self._candidates, user_input.get(CONF_SELECTED, []), rooms
        )
        if failed:
            # bereits angelegte Proxys tauchen beim erneuten Anzeigen als vorhandene Proxys auf
            if new:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, options={**self.config_entry.options, CONF_ROOMS: rooms + new}
                )
            self._candidates = find_candidates(self.hass, rooms + new)
            return self.async_show_form(
                step_id="scan",
                data_schema=_candidates_schema(self._candidates),
                errors={"base": "proxy_failed"},
                description_placeholders={"failed": ", ".join(failed)},
            )
        return self._save(**{CONF_ROOMS: rooms + new})

    # --- Raum von Hand hinzufügen
    def _add_schema(self, d: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_ROOM_CLIMATE, default=d.get(CONF_ROOM_CLIMATE, vol.UNDEFINED)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(CONF_ROOM_AREA, description=_suggested(d.get(CONF_ROOM_AREA))): selector.AreaSelector(),
                vol.Optional(CONF_ROOM_NAME, description=_suggested(d.get(CONF_ROOM_NAME))): selector.TextSelector(),
                vol.Optional(CONF_ROOM_SENSOR, description=_suggested(d.get(CONF_ROOM_SENSOR))): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_CREATE_PROXY, default=d.get(CONF_CREATE_PROXY, True)): selector.BooleanSelector(),
                vol.Optional(CONF_ROOM_ICON, description=_suggested(d.get(CONF_ROOM_ICON))): selector.IconSelector(),
            }
        )

    async def async_step_add_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        rooms = self._rooms
        if user_input is not None:
            hass = self.hass
            climate = user_input[CONF_ROOM_CLIMATE]
            proxy = proxy_for(hass, climate)
            taken = {r[CONF_ROOM_CLIMATE] for r in rooms}
            if climate in taken or (proxy and proxy["climate"] in taken):
                errors[CONF_ROOM_CLIMATE] = "climate_in_use"
            else:
                area = (
                    user_input.get(CONF_ROOM_AREA)
                    or _area_of(hass, proxy["climate"] if proxy else None)
                    or _area_of(hass, user_input.get(CONF_ROOM_SENSOR))
                    or _area_of(hass, climate)
                )
                name = (
                    (user_input.get(CONF_ROOM_NAME) or "").strip()
                    or _area_name(hass, area)
                    or _clean_name(_friendly(hass, proxy["climate"] if proxy else climate))
                )
                sensor = user_input.get(CONF_ROOM_SENSOR)
                create = bool(user_input.get(CONF_CREATE_PROXY)) and proxy is None and is_tado_trv(hass, climate)
                if create and not sensor:
                    sensor = suggest_sensor(hass, area)
                try:
                    room = await async_build_room(
                        hass,
                        {r[CONF_ROOM_ID] for r in rooms},
                        name=name,
                        climate=climate,
                        sensor=sensor,
                        area_id=area,
                        icon=user_input.get(CONF_ROOM_ICON),
                        create_proxy=create,
                    )
                except ProxyCreateError as err:
                    errors["base"] = err.args[0]
                else:
                    return self._save(**{CONF_ROOMS: [*rooms, room]})
        return self.async_show_form(
            step_id="add_room",
            data_schema=self._add_schema(user_input or {}),
            errors=errors,
            description_placeholders=placeholders,
        )

    def _room_select(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("room"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=r[CONF_ROOM_ID], label=r[CONF_ROOM_NAME])
                            for r in self._rooms
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    # --- Raum bearbeiten
    async def async_step_edit_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._room_id = user_input["room"]
            return await self.async_step_edit_room_details()
        return self.async_show_form(step_id="edit_room", data_schema=self._room_select())

    async def async_step_edit_room_details(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        rooms = self._rooms
        room = next(r for r in rooms if r[CONF_ROOM_ID] == self._room_id)
        errors: dict[str, str] = {}
        if user_input is not None:
            if any(
                r[CONF_ROOM_CLIMATE] == user_input[CONF_ROOM_CLIMATE] and r[CONF_ROOM_ID] != self._room_id
                for r in rooms
            ):
                errors[CONF_ROOM_CLIMATE] = "climate_in_use"
            else:
                room.update(
                    {
                        CONF_ROOM_NAME: user_input[CONF_ROOM_NAME],
                        CONF_ROOM_CLIMATE: user_input[CONF_ROOM_CLIMATE],
                        CONF_ROOM_SENSOR: user_input.get(CONF_ROOM_SENSOR),
                        CONF_ROOM_ICON: user_input.get(CONF_ROOM_ICON),
                    }
                )
                return self._save(**{CONF_ROOMS: rooms})
        d = user_input or room
        schema = vol.Schema(
            {
                vol.Required(CONF_ROOM_NAME, default=d.get(CONF_ROOM_NAME, vol.UNDEFINED)): selector.TextSelector(),
                vol.Required(CONF_ROOM_CLIMATE, default=d.get(CONF_ROOM_CLIMATE, vol.UNDEFINED)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(CONF_ROOM_SENSOR, description=_suggested(d.get(CONF_ROOM_SENSOR))): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_ROOM_ICON, description=_suggested(d.get(CONF_ROOM_ICON))): selector.IconSelector(),
            }
        )
        return self.async_show_form(
            step_id="edit_room_details",
            data_schema=schema,
            errors=errors,
            description_placeholders={"room": room[CONF_ROOM_NAME]},
        )

    # --- Raum entfernen
    async def async_step_remove_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            rooms = [r for r in self._rooms if r[CONF_ROOM_ID] != user_input["room"]]
            return self._save(**{CONF_ROOMS: rooms})
        return self.async_show_form(step_id="remove_room", data_schema=self._room_select())

    # --- Einstellungen
    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_days(user_input)
            if not errors:
                return self._save(**user_input)
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(user_input or dict(self.config_entry.options)),
            errors=errors,
        )

