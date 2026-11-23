"""Heizplaner-Engine: berechnet die Stufe je Raum und steuert die Thermostate/Proxys."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntry, ConfigEntryChange
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ALL_STUFEN,
    CONF_BUERO_DAYS,
    CONF_DASHBOARD,
    CONF_HOMEOFFICE_DAYS,
    CONF_ROOM_CLIMATE,
    CONF_ROOM_ID,
    CONF_ROOMS,
    CONF_SUBDIV,
    DAYTYPE_LABELS,
    DEFAULT_BUERO_DAYS,
    DEFAULT_HOMEOFFICE_DAYS,
    DEFAULT_SCHEDULE,
    DEFAULT_SUBDIV,
    PROXY_NUMBER_KEYS,
    PROXY_PRESETS,
    SIGNAL_UPDATE,
    STORAGE_KEY,
    STORAGE_VERSION,
    STUFE_DEFAULTS,
    STUFE_LABELS,
    ST_VERREIST,
    SW_AKTIV,
    SW_FREI,
    SW_HOMEOFFICE,
    SW_VERREIST,
)
from .discovery import PROXY_DOMAIN
from .repairs import async_sync_issues
from .schedule import (
    DayInfo,
    PlanState,
    base_daytype,
    effective_daytype,
    minute_of,
    normalize_points,
    normalize_room_plan,
    stufe_at,
    yesterday,
)

_LOGGER = logging.getLogger(__name__)

# Wartezeit, bis ein fehlgeschlagener/übersprungener Raum erneut versucht wird
RETRY_MINUTES = 5


class Planer:
    """Zentrale Logik eines Heizplaner-Eintrags."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.schedule: dict[str, dict[str, list]] = {}
        self.plan_version = 0
        self.switches: dict[str, bool] = {
            SW_AKTIV: False,
            SW_HOMEOFFICE: False,
            SW_FREI: False,
            SW_VERREIST: False,
        }
        self.stufen: dict[str, float] = dict(STUFE_DEFAULTS)
        self.today: DayInfo | None = None
        self.room_state: dict[str, dict[str, Any]] = {}
        # zuletzt erfolgreich gesendeter Zielzustand je Raum (stufe, ziel)
        self._applied: dict[str, tuple[str, float]] = {}
        self._retry_after: dict[str, datetime] = {}
        self._holidays: Any = None
        self._holiday_years: set[int] = set()
        self._last_date: date | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._dashboard_hash: str | None = None
        self.dashboard_state = "aus"  # aus | automatisch | von Hand geändert | Fehler
        self._dashboard = None
        self._started = False
        self._evaluating = False
        self._pending = False

    # ------------------------------------------------------------------ Konfig
    @property
    def rooms(self) -> list[dict[str, Any]]:
        return list(self.entry.options.get(CONF_ROOMS, []))

    def room(self, room_id: str) -> dict[str, Any] | None:
        return next((r for r in self.rooms if r[CONF_ROOM_ID] == room_id), None)

    @property
    def buero_days(self) -> list[str]:
        return self.entry.options.get(CONF_BUERO_DAYS, DEFAULT_BUERO_DAYS)

    @property
    def homeoffice_days(self) -> list[str]:
        return self.entry.options.get(CONF_HOMEOFFICE_DAYS, DEFAULT_HOMEOFFICE_DAYS)

    @property
    def subdiv(self) -> str:
        return self.entry.options.get(CONF_SUBDIV, DEFAULT_SUBDIV)

    # ------------------------------------------------------------------ Start/Stop
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.schedule = data.get("schedule", {})
        self.plan_version = data.get("version", 0)
        self._dashboard_hash = data.get("dashboard_hash")
        for room in self.rooms:
            self.schedule[room[CONF_ROOM_ID]] = normalize_room_plan(
                self.schedule.get(room[CONF_ROOM_ID], {}), DEFAULT_SCHEDULE
            )

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"schedule": self.schedule, "version": self.plan_version, "dashboard_hash": self._dashboard_hash}
        )

    async def async_start(self) -> None:
        """Nach dem Laden aller Entitäten starten."""
        await self._async_load_holidays(dt_util.now().year)
        self._unsubs.append(async_track_time_change(self.hass, self._tick, second=5))
        climates = [r[CONF_ROOM_CLIMATE] for r in self.rooms]
        if climates:
            self._unsubs.append(
                async_track_state_change_event(self.hass, climates, self._climate_changed)
            )
        self._started = True
        # kurz warten, bis Proxys/Thermostate nach einem Neustart bereit sind
        self._unsubs.append(async_call_later(self.hass, 15, self._delayed_first_run))

        # neue/entfernte Tado X Proxys -> Hinweis „Neuer Raum gefunden“ aktualisieren
        self._unsubs.append(
            async_dispatcher_connect(self.hass, SIGNAL_CONFIG_ENTRY_CHANGED, self._config_entry_changed)
        )

    async def _delayed_first_run(self, _now: datetime) -> None:
        self._sync_issues()
        await self.async_evaluate()

    @callback
    def _config_entry_changed(self, change: ConfigEntryChange, entry: ConfigEntry) -> None:
        if entry.domain != PROXY_DOMAIN:
            return
        # kurz warten, bis der Proxy eingerichtet ist (und ggf. schon als Raum übernommen wurde)
        self._unsubs.append(async_call_later(self.hass, 10, self._delayed_sync))

    @callback
    def _delayed_sync(self, _now: datetime) -> None:
        self._sync_issues()

    @callback
    def _sync_issues(self) -> None:
        if not self._started:
            return
        try:
            async_sync_issues(self.hass, self.rooms)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Suche nach neuen Proxys fehlgeschlagen")

    # ------------------------------------------------------------------ Dashboard
    async def async_setup_dashboard(self) -> None:
        if not self.entry.options.get(CONF_DASHBOARD, True):
            self.dashboard_state = "aus"
            return
        from .dashboard import Dashboard  # noqa: PLC0415

        self._dashboard = Dashboard(self.hass)
        if not self._dashboard.register():
            self.dashboard_state = "Fehler"
            return
        await self.async_update_dashboard(force=False)

    async def async_update_dashboard(self, force: bool) -> None:
        if self._dashboard is None or not self._dashboard.registered:
            return
        from .dashboard import build_config  # noqa: PLC0415

        try:
            config = build_config(self.hass, self.rooms, self._is_proxy)
            new_hash, edited = await self._dashboard.async_update(config, self._dashboard_hash, force)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Dashboard konnte nicht erzeugt werden")
            self.dashboard_state = "Fehler"
            return
        self.dashboard_state = "von Hand geändert" if edited else "automatisch"
        if new_hash != self._dashboard_hash:
            self._dashboard_hash = new_hash
            await self._async_save()
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    async def async_stop(self) -> None:
        if self._dashboard is not None:
            self._dashboard.unregister()
            self._dashboard = None
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._started = False

    # ------------------------------------------------------------------ Feiertage
    async def _async_load_holidays(self, year: int) -> None:
        years = {year, year - 1, year + 1}
        if years <= self._holiday_years and self._holidays is not None:
            return

        def _load() -> Any:
            import holidays  # noqa: PLC0415 - schwerer Import im Executor

            return holidays.country_holidays("DE", subdiv=self.subdiv, years=sorted(years), language="de")

        try:
            self._holidays = await self.hass.async_add_executor_job(_load)
            self._holiday_years = years
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Feiertage für DE-%s konnten nicht geladen werden", self.subdiv)
            self._holidays = {}

    def holiday(self, day: date) -> str | None:
        if not self._holidays:
            return None
        try:
            return self._holidays.get(day)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ Berechnung
    def day_info(self, day: date, with_switches: bool = True) -> DayInfo:
        base = base_daytype(day, self.buero_days, self.homeoffice_days, self.holiday(day))
        if not with_switches:
            return base
        return effective_daytype(base, self.switches[SW_FREI], self.switches[SW_HOMEOFFICE])

    def plan_state(self, room_id: str, now: datetime) -> PlanState:
        today = now.date()
        tt_today = self.day_info(today).daytype
        # gestern ohne Schalter (die gelten nur heute)
        tt_yesterday = self.day_info(yesterday(today), with_switches=False).daytype
        plan = self.schedule.get(room_id) or DEFAULT_SCHEDULE
        return stufe_at(plan[tt_today], plan[tt_yesterday], minute_of(now))

    def desired(self, room_id: str, now: datetime) -> tuple[str, float, PlanState | None]:
        if self.switches[SW_VERREIST]:
            return ST_VERREIST, self.stufen[ST_VERREIST], None
        ps = self.plan_state(room_id, now)
        return ps.stufe, self.stufen[ps.stufe], ps

    @property
    def mode_label(self) -> str:
        if not self.switches[SW_AKTIV]:
            return "Heizplan aus"
        if self.switches[SW_VERREIST]:
            return "Verreist"
        info = self.today
        if info is None:
            return "–"
        if info.reason == "frei":
            return "Frei / zu Hause"
        if info.reason == "feiertag":
            return f"Feiertag · {info.holiday}"
        if info.reason == "homeoffice":
            return "Homeoffice"
        return {"buero": "Bürotag", "homeoffice": "Homeoffice", "wochenende": "Wochenende"}[info.daytype]

    # ------------------------------------------------------------------ Trigger
    async def _tick(self, now: datetime) -> None:
        today = now.date()
        if self._last_date is not None and today != self._last_date:
            # neuer Tag: Homeoffice gilt nur einen Tag
            if self.switches[SW_HOMEOFFICE]:
                self.switches[SW_HOMEOFFICE] = False
                _LOGGER.debug("Homeoffice-Schalter für neuen Tag zurückgesetzt")
            await self._async_load_holidays(today.year)
        self._last_date = today
        await self.async_evaluate()

    @callback
    def _climate_changed(self, event: Event) -> None:
        # nur Anzeige aktualisieren (manuell/Boost); gesteuert wird im Takt
        self._refresh_room_states(dt_util.now())
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    async def async_set_switch(self, key: str, value: bool) -> None:
        if self.switches.get(key) == value:
            return
        self.switches[key] = value
        if key == SW_AKTIV and value:
            # beim Einschalten alles neu senden
            self._applied.clear()
            self._retry_after.clear()
        await self.async_evaluate()

    async def async_set_stufe(self, key: str, value: float) -> None:
        if key not in ALL_STUFEN:
            return
        self.stufen[key] = float(value)
        if self._started:
            await self.async_evaluate()

    async def async_apply_now(self) -> None:
        self._applied.clear()
        self._retry_after.clear()
        await self.async_evaluate()

    async def async_set_room_plan(self, room_id: str, daytype: str, points: list) -> None:
        if self.room(room_id) is None:
            raise ValueError(f"Unbekannter Raum: {room_id}")
        if daytype not in DAYTYPE_LABELS:
            raise ValueError(f"Unbekannter Tagtyp: {daytype}")
        plan = self.schedule.setdefault(room_id, normalize_room_plan({}, DEFAULT_SCHEDULE))
        plan[daytype] = normalize_points(points)
        self.plan_version += 1
        await self._async_save()
        await self.async_evaluate()

    async def async_rooms_changed(self) -> None:
        """Räume wurden geändert (Optionen) – Pläne ergänzen/aufräumen."""
        ids = {r[CONF_ROOM_ID] for r in self.rooms}
        for rid in list(self.schedule):
            if rid not in ids:
                self.schedule.pop(rid)
        for rid in ids:
            self.schedule[rid] = normalize_room_plan(self.schedule.get(rid, {}), DEFAULT_SCHEDULE)
        await self._async_save()

    # ------------------------------------------------------------------ Steuerung
    async def async_evaluate(self) -> None:
        """Pläne auswerten und – falls nötig – an die Geräte senden."""
        if self._evaluating:
            self._pending = True
            return
        self._evaluating = True
        try:
            while True:
                self._pending = False
                await self._evaluate_once()
                if not self._pending:
                    break
        finally:
            self._evaluating = False

    async def _evaluate_once(self) -> None:
        now = dt_util.now()
        self.today = self.day_info(now.date())
        if self.switches[SW_AKTIV] and self._started:
            # Preset-Temperaturen der Proxys zuerst angleichen (sendet nur bei Abweichung)
            await self.async_sync_proxy_numbers()
            for room in self.rooms:
                await self._apply_room(room, now)
        self._refresh_room_states(now)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    def _is_proxy(self, entity_id: str) -> bool:
        st = self.hass.states.get(entity_id)
        return bool(st and ("target_for_tado_c" in st.attributes or "user_preset" in st.attributes))

    def _matches(self, entity_id: str, stufe: str, ziel: float) -> bool:
        """Ist das Gerät schon im gewünschten Zustand?"""
        st = self.hass.states.get(entity_id)
        if st is None:
            return False
        temp = st.attributes.get("temperature")
        temp_ok = temp is not None and abs(float(temp) - ziel) < 0.05
        if self._is_proxy(entity_id):
            preset = PROXY_PRESETS.get(stufe)
            user_preset = st.attributes.get("user_preset", st.attributes.get("preset_mode"))
            if preset:
                return user_preset == preset and temp_ok
            return temp_ok and user_preset in (None, "none")
        return temp_ok

    async def _apply_room(self, room: dict[str, Any], now: datetime) -> None:
        rid = room[CONF_ROOM_ID]
        entity_id = room[CONF_ROOM_CLIMATE]
        stufe, ziel, _ps = self.desired(rid, now)
        target = (stufe, round(ziel, 1))
        if self._applied.get(rid) == target:
            return  # schon gesendet – manuelle Änderungen bleiben bis zum nächsten Wechsel
        retry = self._retry_after.get(rid)
        if retry and now < retry:
            return
        st = self.hass.states.get(entity_id)
        if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, STATE_OFF):
            self._retry_after[rid] = now + _minutes(RETRY_MINUTES)
            return
        if st.attributes.get("preset_mode") == "boost":
            # laufenden Boost nicht abbrechen, danach erneut versuchen
            self._retry_after[rid] = now + _minutes(1)
            return
        if self._matches(entity_id, stufe, ziel):
            self._applied[rid] = target
            self._retry_after.pop(rid, None)
            return
        try:
            preset = PROXY_PRESETS.get(stufe) if self._is_proxy(entity_id) else None
            if preset:
                await self.hass.services.async_call(
                    "climate",
                    "set_preset_mode",
                    {ATTR_ENTITY_ID: entity_id, "preset_mode": preset},
                    blocking=True,
                )
            else:
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {ATTR_ENTITY_ID: entity_id, "temperature": round(ziel, 1)},
                    blocking=True,
                )
            self._applied[rid] = target
            self._retry_after.pop(rid, None)
            _LOGGER.info("%s -> %s %.1f °C", room.get("name", rid), STUFE_LABELS[stufe], ziel)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Konnte %s nicht setzen: %s", entity_id, err)
            self._retry_after[rid] = now + _minutes(RETRY_MINUTES)

    def _proxy_numbers(self, climate_entity: str) -> dict[str, str]:
        """Preset-Zahlen (Komfort/Eco/Abwesend) am Gerät des Proxys finden."""
        reg = er.async_get(self.hass)
        ent = reg.async_get(climate_entity)
        if ent is None or ent.device_id is None:
            return {}
        found: dict[str, str] = {}
        for e in er.async_entries_for_device(reg, ent.device_id):
            if e.domain != "number":
                continue
            key = f"{e.entity_id} {e.translation_key or ''}".lower()
            for stufe, words in PROXY_NUMBER_KEYS.items():
                if stufe not in found and any(w in key for w in words) and "boost" not in key:
                    found[stufe] = e.entity_id
        return found

    async def async_sync_proxy_numbers(self) -> None:
        """Komfort/Eco/Verreist der Stufen in die Presets aller Proxys schreiben."""
        for room in self.rooms:
            entity_id = room[CONF_ROOM_CLIMATE]
            if not self._is_proxy(entity_id):
                continue
            for stufe, number_entity in self._proxy_numbers(entity_id).items():
                st = self.hass.states.get(number_entity)
                value = round(self.stufen[stufe], 1)
                if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                    continue
                try:
                    if abs(float(st.state) - value) < 0.05:
                        continue
                except ValueError:
                    pass
                try:
                    await self.hass.services.async_call(
                        "number",
                        "set_value",
                        {ATTR_ENTITY_ID: number_entity, "value": value},
                        blocking=True,
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Konnte %s nicht setzen: %s", number_entity, err)

    # ------------------------------------------------------------------ Anzeige
    def _refresh_room_states(self, now: datetime) -> None:
        for room in self.rooms:
            rid = room[CONF_ROOM_ID]
            stufe, ziel, ps = self.desired(rid, now)
            entity_id = room[CONF_ROOM_CLIMATE]
            st = self.hass.states.get(entity_id)
            device_target = st.attributes.get("temperature") if st else None
            preset = st.attributes.get("preset_mode") if st else None
            manuell = (
                self.switches[SW_AKTIV]
                and self._applied.get(rid) == (stufe, round(ziel, 1))
                and st is not None
                and st.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
                and preset != "boost"
                and not self._matches(entity_id, stufe, ziel)
            )
            self.room_state[rid] = {
                "stufe": stufe,
                "stufe_label": STUFE_LABELS[stufe],
                "ziel": round(ziel, 1),
                "seit": ps.since if ps else None,
                "naechster_wechsel": ps.next_time if ps else None,
                "naechste_stufe": ps.next_stufe if ps else None,
                "naechste_stufe_label": STUFE_LABELS.get(ps.next_stufe) if ps and ps.next_stufe else None,
                "geraet_soll": device_target,
                "boost": preset == "boost",
                "manuell": bool(manuell),
                "proxy": self._is_proxy(entity_id),
            }


def _minutes(n: int) -> timedelta:
    return timedelta(minutes=n)
