"""Einrichtung und Optionen (Räume, Tagtypen, Bundesland)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BUERO_DAYS,
    CONF_HOMEOFFICE_DAYS,
    CONF_ROOM_CLIMATE,
    CONF_ROOM_ICON,
    CONF_ROOM_ID,
    CONF_ROOM_NAME,
    CONF_ROOM_SENSOR,
    CONF_ROOMS,
    CONF_SUBDIV,
    DEFAULT_BUERO_DAYS,
    DEFAULT_HOMEOFFICE_DAYS,
    DEFAULT_SUBDIV,
    DOMAIN,
    SUBDIVISIONS,
    WEEKDAY_LABELS,
    WEEKDAYS,
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
        }
    )


def _room_schema(defaults: dict[str, Any]) -> vol.Schema:
    schema: dict[Any, Any] = {
        vol.Required(CONF_ROOM_NAME, default=defaults.get(CONF_ROOM_NAME, vol.UNDEFINED)): selector.TextSelector(),
        vol.Required(
            CONF_ROOM_CLIMATE, default=defaults.get(CONF_ROOM_CLIMATE, vol.UNDEFINED)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="climate")),
    }
    sensor_default = defaults.get(CONF_ROOM_SENSOR)
    schema[
        vol.Optional(CONF_ROOM_SENSOR, description={"suggested_value": sensor_default} if sensor_default else None)
    ] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature"))
    icon_default = defaults.get(CONF_ROOM_ICON)
    schema[
        vol.Optional(CONF_ROOM_ICON, description={"suggested_value": icon_default} if icon_default else None)
    ] = selector.IconSelector()
    return vol.Schema(schema)


def _check_days(user_input: dict[str, Any]) -> dict[str, str]:
    if set(user_input[CONF_BUERO_DAYS]) & set(user_input[CONF_HOMEOFFICE_DAYS]):
        return {"base": "days_overlap"}
    return {}


class HeizplanerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einrichtung: einmal pro Installation."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_days(user_input)
            if not errors:
                return self.async_create_entry(title="Heizplaner", data={}, options={**user_input, CONF_ROOMS: []})
        return self.async_show_form(step_id="user", data_schema=_settings_schema(user_input or {}), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HeizplanerOptionsFlow()


class HeizplanerOptionsFlow(OptionsFlow):
    """Räume verwalten und Einstellungen ändern."""

    def __init__(self) -> None:
        self._room_id: str | None = None

    @property
    def _rooms(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.config_entry.options.get(CONF_ROOMS, [])]

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["add_room"]
        if self._rooms:
            menu += ["edit_room", "remove_room"]
        menu.append("settings")
        return self.async_show_menu(step_id="init", menu_options=menu)

    # --- Raum hinzufügen
    async def async_step_add_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        rooms = self._rooms
        if user_input is not None:
            if any(r[CONF_ROOM_CLIMATE] == user_input[CONF_ROOM_CLIMATE] for r in rooms):
                errors[CONF_ROOM_CLIMATE] = "climate_in_use"
            else:
                from . import slugify_room  # noqa: PLC0415

                rooms.append(
                    {
                        CONF_ROOM_ID: slugify_room(user_input[CONF_ROOM_NAME], {r[CONF_ROOM_ID] for r in rooms}),
                        CONF_ROOM_NAME: user_input[CONF_ROOM_NAME],
                        CONF_ROOM_CLIMATE: user_input[CONF_ROOM_CLIMATE],
                        CONF_ROOM_SENSOR: user_input.get(CONF_ROOM_SENSOR),
                        CONF_ROOM_ICON: user_input.get(CONF_ROOM_ICON),
                    }
                )
                return self._save(**{CONF_ROOMS: rooms})
        return self.async_show_form(step_id="add_room", data_schema=_room_schema(user_input or {}), errors=errors)

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
        return self.async_show_form(
            step_id="edit_room_details",
            data_schema=_room_schema(user_input or room),
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
