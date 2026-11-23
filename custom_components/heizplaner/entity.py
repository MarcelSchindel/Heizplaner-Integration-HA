"""Gemeinsame Basis der Heizplaner-Entitäten."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATE, VERSION
from .planer import Planer


class HeizplanerEntity(Entity):
    """Alle Entitäten hängen an einem Gerät „Heizplaner“."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, planer: Planer, key: str) -> None:
        self.planer = planer
        self._attr_unique_id = f"{planer.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, planer.entry.entry_id)},
            name="Heizplaner",
            manufacturer="Marcel",
            model="Wochenplan",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self.async_write_ha_state))
