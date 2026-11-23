"""Schalter: Heizplan, Homeoffice, Frei, Verreist."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import HeizplanerConfigEntry
from .const import SW_HOMEOFFICE, SWITCHES
from .entity import HeizplanerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeizplanerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(PlanSwitch(entry.runtime_data, key) for key in SWITCHES)


class PlanSwitch(HeizplanerEntity, SwitchEntity, RestoreEntity):
    """Schaltet einen Modus des Heizplans."""

    def __init__(self, planer, key: str) -> None:
        super().__init__(planer, f"switch_{key}")
        self._key = key
        self._attr_name, self._attr_icon = SWITCHES[key]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        on = last.state == STATE_ON
        if self._key == SW_HOMEOFFICE and on:
            # Homeoffice gilt nur für den Tag, an dem es eingeschaltet wurde
            on = dt_util.as_local(last.last_changed).date() == dt_util.now().date()
        self.planer.switches[self._key] = on

    @property
    def is_on(self) -> bool:
        return self.planer.switches[self._key]

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.planer.async_set_switch(self._key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.planer.async_set_switch(self._key, False)
