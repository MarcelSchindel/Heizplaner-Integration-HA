"""Reparatur-Hinweis „Neuer Tado X Proxy gefunden“ mit Übernahme-Dialog."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir, selector

from .const import CONF_ROOM_ID, CONF_ROOMS, DOMAIN
from .discovery import ProxyCreateError, async_build_room


class NewProxyFlow(RepairsFlow):
    """Gefundenen Proxy als Raum übernehmen."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entries = self.hass.config_entries.async_loaded_entries(DOMAIN)
            if not entries:
                return self.async_abort(reason="not_setup")
            entry = entries[0]
            rooms = [dict(r) for r in entry.options.get(CONF_ROOMS, [])]
            try:
                room = await async_build_room(
                    self.hass,
                    {r[CONF_ROOM_ID] for r in rooms},
                    name=user_input["name"].strip() or self._data["name"],
                    climate=self._data["climate"],
                    sensor=self._data.get("sensor"),
                    area_id=self._data.get("area_id"),
                    icon=None,
                    create_proxy=False,
                )
            except ProxyCreateError as err:
                errors["base"] = err.args[0]
            else:
                self.hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_ROOMS: [*rooms, room]})
                return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {vol.Required("name", default=self._data["name"]): selector.TextSelector()}
            ),
            errors=errors,
            description_placeholders={"climate": self._data["climate"]},
        )


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None) -> RepairsFlow:
    return NewProxyFlow(data or {})


def issue_id_for(proxy_entry_id: str) -> str:
    return f"new_proxy_{proxy_entry_id}"


def async_sync_issues(hass: HomeAssistant, rooms: list[dict[str, Any]]) -> None:
    """Für jeden Proxy, der noch keinem Raum gehört, einen Hinweis anlegen – erledigte entfernen."""
    from .discovery import KIND_PROXY, find_candidates  # noqa: PLC0415

    wanted = {}
    for cand in find_candidates(hass, rooms):
        if cand.kind == KIND_PROXY and cand.proxy_entry_id:
            wanted[issue_id_for(cand.proxy_entry_id)] = cand
    reg = ir.async_get(hass)
    for (domain, issue_id), _issue in list(reg.issues.items()):
        if domain == DOMAIN and issue_id.startswith("new_proxy_") and issue_id not in wanted:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
    for issue_id, cand in wanted.items():
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="new_proxy",
            translation_placeholders={"name": cand.name, "climate": cand.climate},
            data={"climate": cand.climate, "name": cand.name, "sensor": cand.sensor, "area_id": cand.area_id},
        )
