"""Knopf: Plan sofort neu anwenden (überschreibt manuelle Änderungen)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeizplanerConfigEntry
from .entity import HeizplanerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeizplanerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([ApplyButton(entry.runtime_data)])


class ApplyButton(HeizplanerEntity, ButtonEntity):
    _attr_name = "Plan jetzt anwenden"
    _attr_icon = "mdi:calendar-sync"

    def __init__(self, planer) -> None:
        super().__init__(planer, "apply_now")

    async def async_press(self) -> None:
        await self.planer.async_apply_now()
