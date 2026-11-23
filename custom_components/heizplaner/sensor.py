"""Sensoren: Modus des Tages und Plan je Raum."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeizplanerConfigEntry
from .const import CONF_ROOM_CLIMATE, CONF_ROOM_ICON, CONF_ROOM_ID, CONF_ROOM_NAME, DAYTYPE_LABELS, SW_AKTIV
from .entity import HeizplanerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeizplanerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    planer = entry.runtime_data
    entities: list[SensorEntity] = [ModeSensor(planer)]
    entities += [RoomPlanSensor(planer, room) for room in planer.rooms]
    async_add_entities(entities)


class ModeSensor(HeizplanerEntity, SensorEntity):
    """Was heute gilt (Bürotag, Homeoffice, Frei, Feiertag …)."""

    _attr_name = "Modus"

    def __init__(self, planer) -> None:
        super().__init__(planer, "modus")

    @property
    def native_value(self) -> str:
        return self.planer.mode_label

    @property
    def icon(self) -> str:
        label = self.planer.mode_label
        if label == "Heizplan aus":
            return "mdi:pause-circle-outline"
        if label == "Verreist":
            return "mdi:airplane"
        info = self.planer.today
        if info and info.reason == "frei":
            return "mdi:beach"
        if info and info.reason == "feiertag":
            return "mdi:party-popper"
        return {"buero": "mdi:office-building", "homeoffice": "mdi:laptop", "wochenende": "mdi:home-heart"}.get(
            info.daytype if info else "", "mdi:calendar"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.planer.today
        return {
            "tagtyp": info.daytype if info else None,
            "tagtyp_label": DAYTYPE_LABELS.get(info.daytype) if info else None,
            "grund": info.reason if info else None,
            "feiertag": info.holiday if info else None,
            "plan_version": self.planer.plan_version,
            "aktiv": self.planer.switches[SW_AKTIV],
            "dashboard": self.planer.dashboard_state,
        }


class RoomPlanSensor(HeizplanerEntity, SensorEntity):
    """Plan-Status eines Raums, z. B. „Komfort 21.0 °C · ab 22:30 Nacht“."""

    def __init__(self, planer, room: dict[str, Any]) -> None:
        super().__init__(planer, f"room_{room[CONF_ROOM_ID]}")
        self._room_id = room[CONF_ROOM_ID]
        self._attr_name = room[CONF_ROOM_NAME]
        self._attr_icon = room.get(CONF_ROOM_ICON) or "mdi:home-thermometer"
        self._climate = room[CONF_ROOM_CLIMATE]

    @property
    def _rs(self) -> dict[str, Any]:
        return self.planer.room_state.get(self._room_id, {})

    @property
    def native_value(self) -> str | None:
        rs = self._rs
        if not rs:
            return None
        text = f"{rs['stufe_label']} {rs['ziel']:.1f} °C"
        if rs.get("naechster_wechsel"):
            text += f" · ab {rs['naechster_wechsel']} {rs['naechste_stufe_label']}"
        return text

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"raum_id": self._room_id, "thermostat": self._climate, **self._rs}
