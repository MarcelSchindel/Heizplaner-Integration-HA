"""Thermostate und Tado X Proxys finden – und Proxys anlegen."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, UnknownHandler
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

from .const import (
    CONF_ROOM_AREA,
    CONF_ROOM_CLIMATE,
    CONF_ROOM_ICON,
    CONF_ROOM_ID,
    CONF_ROOM_NAME,
    CONF_ROOM_PROXY_ENTRY,
    CONF_ROOM_SENSOR,
)

_LOGGER = logging.getLogger(__name__)

PROXY_DOMAIN = "tadox_proxy"
PROXY_CONF_SOURCE = "source_entity_id"
PROXY_CONF_SENSOR = "external_temperature_entity_id"
PROXY_CONF_NAME = "name"

KIND_PROXY = "proxy"  # vorhandener Tado X Proxy
KIND_TADO = "tado"  # Tado-Thermostat ohne Proxy -> Proxy wird angelegt
KIND_OTHER = "other"  # anderes Thermostat -> wird direkt gesteuert

_ROOM_ICONS = [
    (r"wohn|lounge|living", "mdi:sofa"),
    (r"ess|dining", "mdi:silverware-fork-knife"),
    (r"schlaf|bed", "mdi:bed"),
    (r"kind|baby", "mdi:teddy-bear"),
    (r"büro|buero|office|arbeit", "mdi:desk"),
    (r"bad|dusch|wc|bath", "mdi:shower"),
    (r"küche|kueche|kitchen", "mdi:stove"),
    (r"flur|diele|hall", "mdi:door"),
    (r"gast|gäst|guest", "mdi:bed-outline"),
]


class ProxyCreateError(Exception):
    """Proxy konnte nicht angelegt werden. args[0] = Fehlerschlüssel für die Übersetzung."""


@dataclass
class Candidate:
    """Ein Raum, den der Heizplaner vorschlägt."""

    kind: str
    climate: str  # Proxy- oder Thermostat-Entität
    trv: str | None  # Thermostatkopf (bei Proxy / Tado)
    name: str
    sensor: str | None
    area_id: str | None
    icon: str
    proxy_entry_id: str | None = None

    @property
    def key(self) -> str:
        return self.climate

    def label(self) -> str:
        sensor = f" · Sensor {self.sensor}" if self.sensor else " · kein Raumsensor"
        if self.kind == KIND_PROXY:
            return f"{self.name} – Tado X Proxy ({self.climate}){sensor}"
        if self.kind == KIND_TADO:
            how = "Proxy wird angelegt" if self.sensor else "ohne Sensor: direkt gesteuert"
            return f"{self.name} – Tado-Thermostat ({self.climate}), {how}{sensor}"
        return f"{self.name} – Thermostat ({self.climate}), direkt gesteuert"


def room_icon(name: str) -> str:
    low = name.lower()
    return next((icon for pat, icon in _ROOM_ICONS if re.search(pat, low)), "mdi:home-thermometer")


def _entry_value(entry: ConfigEntry, key: str) -> Any:
    return entry.options.get(key, entry.data.get(key))


def _area_of(hass: HomeAssistant, entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    ent = er.async_get(hass).async_get(entity_id)
    if ent is None:
        return None
    if ent.area_id:
        return ent.area_id
    if ent.device_id and (dev := dr.async_get(hass).async_get(ent.device_id)):
        return dev.area_id
    return None


def _area_name(hass: HomeAssistant, area_id: str | None) -> str | None:
    if area_id and (area := ar.async_get(hass).async_get_area(area_id)):
        return area.name
    return None


def _friendly(hass: HomeAssistant, entity_id: str) -> str:
    st = hass.states.get(entity_id)
    return (st.name if st else None) or entity_id.split(".", 1)[1].replace("_", " ").title()


def _clean_name(name: str) -> str:
    """„Tado X Proxy Büro“ -> „Büro“, „Thermostat Esszimmer OG“ -> „Esszimmer OG“."""
    out = re.sub(r"(?i)\b(tado\s*x\s*proxy|proxy|thermostat|heizung|heizkörper|trv)\b", "", name)
    return re.sub(r"\s{2,}", " ", out).strip(" -·") or name


def proxy_entries(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Alle Tado X Proxys mit Thermostat, Sensor und Climate-Entität."""
    reg = er.async_get(hass)
    out = []
    for entry in hass.config_entries.async_entries(PROXY_DOMAIN):
        climate = next(
            (e.entity_id for e in er.async_entries_for_config_entry(reg, entry.entry_id) if e.domain == "climate"),
            None,
        )
        out.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "climate": climate,
                "trv": _entry_value(entry, PROXY_CONF_SOURCE),
                "sensor": _entry_value(entry, PROXY_CONF_SENSOR),
            }
        )
    return out


def is_tado_trv(hass: HomeAssistant, entity_id: str) -> bool:
    ent = er.async_get(hass).async_get(entity_id)
    if ent is None or ent.device_id is None or ent.platform == PROXY_DOMAIN:
        return False
    dev = dr.async_get(hass).async_get(ent.device_id)
    return bool(dev and "tado" in (dev.manufacturer or "").lower())


def suggest_sensor(hass: HomeAssistant, area_id: str | None) -> str | None:
    """Bester Temperatursensor in einem Bereich (keine Thermostat-Fühler)."""
    if not area_id:
        return None
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    climate_devices = {e.device_id for e in ent_reg.entities.values() if e.domain == "climate" and e.device_id}
    humidity_devices = {
        e.device_id
        for e in ent_reg.entities.values()
        if e.domain == "sensor" and e.device_id and (e.device_class or e.original_device_class) == "humidity"
    }
    best: tuple[int, str] | None = None
    for e in ent_reg.entities.values():
        if e.domain != "sensor" or e.disabled_by or (e.device_class or e.original_device_class) != "temperature":
            continue
        dev = dev_reg.async_get(e.device_id) if e.device_id else None
        area = e.area_id or (dev.area_id if dev else None)
        if area != area_id or e.device_id in climate_devices or e.platform == PROXY_DOMAIN:
            continue
        st = hass.states.get(e.entity_id)
        if st is None or st.state in ("unavailable", "unknown"):
            continue
        score = 0
        if e.device_id in humidity_devices:
            score += 2  # eigener Klimasensor (Temperatur + Feuchte)
        if e.platform in ("alexa_devices", "alexa_media", "sonos", "hue"):
            score -= 1  # Geräte mit eigener Abwärme
        if best is None or score > best[0]:
            best = (score, e.entity_id)
    return best[1] if best else None


def used_climates(hass: HomeAssistant, rooms: list[dict[str, Any]]) -> set[str]:
    """Climate-Entitäten, die schon zu einem Raum gehören – inkl. Thermostat hinter dem Proxy."""
    used = {r[CONF_ROOM_CLIMATE] for r in rooms}
    for p in proxy_entries(hass):
        if p["climate"] in used and p["trv"]:
            used.add(p["trv"])
        if p["trv"] in used and p["climate"]:
            used.add(p["climate"])
    return used


def find_candidates(hass: HomeAssistant, rooms: list[dict[str, Any]]) -> list[Candidate]:
    """Vorschläge: vorhandene Proxys, Tado-Thermostate ohne Proxy, andere Thermostate."""
    used = used_climates(hass, rooms)
    proxies = proxy_entries(hass)
    wrapped = {p["trv"] for p in proxies if p["trv"]}
    out: list[Candidate] = []

    for p in proxies:
        if not p["climate"] or p["climate"] in used:
            continue
        area = _area_of(hass, p["climate"]) or _area_of(hass, p["sensor"]) or _area_of(hass, p["trv"])
        name = _area_name(hass, area) or _clean_name(p["title"])
        out.append(
            Candidate(KIND_PROXY, p["climate"], p["trv"], name, p["sensor"], area, room_icon(name), p["entry_id"])
        )

    ent_reg = er.async_get(hass)
    for entity_id in sorted(hass.states.async_entity_ids("climate")):
        if entity_id in used or entity_id in wrapped:
            continue
        ent = ent_reg.async_get(entity_id)
        if ent is not None and ent.platform in (PROXY_DOMAIN, "heizplaner"):
            continue
        area = _area_of(hass, entity_id)
        name = _area_name(hass, area) or _clean_name(_friendly(hass, entity_id))
        if is_tado_trv(hass, entity_id):
            sensor = suggest_sensor(hass, area)
            out.append(Candidate(KIND_TADO, entity_id, entity_id, name, sensor, area, room_icon(name)))
        else:
            out.append(Candidate(KIND_OTHER, entity_id, None, name, None, area, room_icon(name)))
    return out


async def async_create_proxy(
    hass: HomeAssistant, trv: str, sensor: str, name: str, area_id: str | None
) -> tuple[str, str]:
    """Legt über den Einrichtungsdialog des Tado X Proxy einen Proxy an.

    Gibt (climate_entity_id, config_entry_id) zurück.
    """
    try:
        result = await hass.config_entries.flow.async_init(PROXY_DOMAIN, context={"source": SOURCE_USER})
    except UnknownHandler as err:
        raise ProxyCreateError("proxy_not_installed") from err
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Tado X Proxy: Einrichtung nicht startbar: %s", err)
        raise ProxyCreateError("proxy_failed") from err

    if result["type"] != FlowResultType.FORM or result.get("step_id") != "user":
        if result["type"] == FlowResultType.FORM:
            hass.config_entries.flow.async_abort(result["flow_id"])
        raise ProxyCreateError("proxy_incompatible")
    fields = {str(k) for k in result["data_schema"].schema} if result.get("data_schema") else set()
    if not {PROXY_CONF_SOURCE, PROXY_CONF_SENSOR, PROXY_CONF_NAME} <= fields:
        hass.config_entries.flow.async_abort(result["flow_id"])
        raise ProxyCreateError("proxy_incompatible")

    try:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {PROXY_CONF_SOURCE: trv, PROXY_CONF_SENSOR: sensor, PROXY_CONF_NAME: name},
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Tado X Proxy konnte nicht angelegt werden: %s", err)
        raise ProxyCreateError("proxy_failed") from err

    if result["type"] == FlowResultType.ABORT:
        raise ProxyCreateError("proxy_exists" if result.get("reason") == "already_configured" else "proxy_failed")
    if result["type"] != FlowResultType.CREATE_ENTRY:
        if result["type"] == FlowResultType.FORM:
            hass.config_entries.flow.async_abort(result["flow_id"])
        raise ProxyCreateError("proxy_failed")

    entry = result["result"]
    ent_reg = er.async_get(hass)
    climate = next(
        (e for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id) if e.domain == "climate"), None
    )
    if climate is None:
        raise ProxyCreateError("proxy_failed")
    if area_id and climate.device_id:
        dr.async_get(hass).async_update_device(climate.device_id, area_id=area_id)
    _LOGGER.info("Tado X Proxy „%s“ angelegt: %s", name, climate.entity_id)
    return climate.entity_id, entry.entry_id


def proxy_for(hass: HomeAssistant, climate: str) -> dict[str, Any] | None:
    """Proxy, zu dem diese Entität gehört (als Proxy oder als Thermostat dahinter)."""
    return next((p for p in proxy_entries(hass) if climate in (p["climate"], p["trv"])), None)


def slugify_room(name: str, existing: set[str]) -> str:
    trans = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
    base = re.sub(r"[^a-z0-9]+", "_", name.lower().translate(trans)).strip("_") or "raum"
    slug, n = base, 2
    while slug in existing:
        slug, n = f"{base}_{n}", n + 1
    return slug


async def async_build_room(
    hass: HomeAssistant,
    existing_ids: set[str],
    *,
    name: str,
    climate: str,
    sensor: str | None,
    area_id: str | None,
    icon: str | None,
    create_proxy: bool,
) -> dict[str, Any]:
    """Raum-Eintrag bauen. Legt bei Bedarf einen Tado X Proxy an (ProxyCreateError bei Fehler)."""
    proxy_entry_id = None
    proxy = proxy_for(hass, climate)
    if proxy and proxy["climate"]:
        # Proxy gibt es schon (auch wenn das Thermostat dahinter gewählt wurde)
        climate = proxy["climate"]
        proxy_entry_id = proxy["entry_id"]
        sensor = sensor or proxy["sensor"]
    elif create_proxy and is_tado_trv(hass, climate):
        if not sensor:
            raise ProxyCreateError("sensor_required")
        climate, proxy_entry_id = await async_create_proxy(hass, climate, sensor, f"Tado X Proxy {name}", area_id)
    return {
        CONF_ROOM_ID: slugify_room(name, existing_ids),
        CONF_ROOM_NAME: name,
        CONF_ROOM_CLIMATE: climate,
        CONF_ROOM_SENSOR: sensor,
        CONF_ROOM_ICON: icon or room_icon(name),
        CONF_ROOM_AREA: area_id,
        CONF_ROOM_PROXY_ENTRY: proxy_entry_id,
    }
