"""Temperatur-Stufen (bleiben über Neustarts erhalten)."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberMode, RestoreNumber
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeizplanerConfigEntry
from .const import ALL_STUFEN, ST_VERREIST, STUFE_ICONS, STUFE_LABELS
from .entity import HeizplanerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeizplanerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(StufeNumber(entry.runtime_data, s) for s in ALL_STUFEN)


class StufeNumber(HeizplanerEntity, RestoreNumber):
    """Solltemperatur einer Stufe."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(self, planer, stufe: str) -> None:
        super().__init__(planer, f"stufe_{stufe}")
        self._stufe = stufe
        self._attr_name = STUFE_LABELS[stufe]
        self._attr_icon = STUFE_ICONS[stufe]
        self._attr_native_min_value = 5.0 if stufe == ST_VERREIST else 12.0
        self._attr_native_max_value = 18.0 if stufe == ST_VERREIST else 25.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self.planer.stufen[self._stufe] = float(last.native_value)

    @property
    def native_value(self) -> float:
        return self.planer.stufen[self._stufe]

    async def async_set_native_value(self, value: float) -> None:
        await self.planer.async_set_stufe(self._stufe, value)
