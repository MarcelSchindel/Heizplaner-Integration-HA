"""Konstanten für den Heizplaner."""

from __future__ import annotations

DOMAIN = "heizplaner"
VERSION = "0.3.1"

CARD_URL = f"/{DOMAIN}/heizplaner-card.js"

STORAGE_KEY = f"{DOMAIN}.plan"
STORAGE_VERSION = 1

# Optionen des Config-Eintrags
CONF_ROOMS = "rooms"
CONF_BUERO_DAYS = "buero_days"
CONF_HOMEOFFICE_DAYS = "homeoffice_days"
CONF_SUBDIV = "subdiv"
CONF_ROOM_ID = "id"
CONF_ROOM_NAME = "name"
CONF_ROOM_CLIMATE = "climate_entity"
CONF_ROOM_SENSOR = "sensor_entity"
CONF_ROOM_ICON = "icon"
CONF_ROOM_AREA = "area_id"
CONF_ROOM_PROXY_ENTRY = "proxy_entry_id"
CONF_CREATE_PROXY = "create_proxy"
CONF_SELECTED = "rooms_selected"
CONF_DASHBOARD = "dashboard"

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_LABELS = {
    "mon": "Montag",
    "tue": "Dienstag",
    "wed": "Mittwoch",
    "thu": "Donnerstag",
    "fri": "Freitag",
    "sat": "Samstag",
    "sun": "Sonntag",
}
DEFAULT_BUERO_DAYS = ["mon", "tue", "wed"]
DEFAULT_HOMEOFFICE_DAYS = ["thu", "fri"]
DEFAULT_SUBDIV = "RP"

SUBDIVISIONS = {
    "BW": "Baden-Württemberg",
    "BY": "Bayern",
    "BE": "Berlin",
    "BB": "Brandenburg",
    "HB": "Bremen",
    "HH": "Hamburg",
    "HE": "Hessen",
    "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz",
    "SL": "Saarland",
    "SN": "Sachsen",
    "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein",
    "TH": "Thüringen",
}

# Tagtypen
TT_BUERO = "buero"
TT_HOMEOFFICE = "homeoffice"
TT_WOCHENENDE = "wochenende"
DAYTYPES = [TT_BUERO, TT_HOMEOFFICE, TT_WOCHENENDE]
DAYTYPE_LABELS = {
    TT_BUERO: "Bürotag",
    TT_HOMEOFFICE: "Homeoffice",
    TT_WOCHENENDE: "Wochenende",
}

# Stufen (die im Plan vorkommen können) + Verreist
ST_KOMFORT = "komfort"
ST_ECO = "eco"
ST_NACHT = "nacht"
ST_SCHLAFEN = "schlafen"
ST_VERREIST = "verreist"
PLAN_STUFEN = [ST_KOMFORT, ST_ECO, ST_NACHT, ST_SCHLAFEN]
ALL_STUFEN = [*PLAN_STUFEN, ST_VERREIST]

STUFE_LABELS = {
    ST_KOMFORT: "Komfort",
    ST_ECO: "Eco",
    ST_NACHT: "Nacht",
    ST_SCHLAFEN: "Schlafen",
    ST_VERREIST: "Verreist",
}
STUFE_ICONS = {
    ST_KOMFORT: "mdi:sofa",
    ST_ECO: "mdi:leaf",
    ST_NACHT: "mdi:weather-night",
    ST_SCHLAFEN: "mdi:bed",
    ST_VERREIST: "mdi:airplane",
}
STUFE_COLORS = {
    ST_KOMFORT: "#ff9800",
    ST_ECO: "#4caf50",
    ST_NACHT: "#3f6ad8",
    ST_SCHLAFEN: "#9c27b0",
    ST_VERREIST: "#9e9e9e",
}
# Startwerte der Stufen (werden danach gespeichert, nicht zurückgesetzt)
STUFE_DEFAULTS = {
    ST_KOMFORT: 21.0,
    ST_ECO: 19.5,
    ST_NACHT: 19.0,
    ST_SCHLAFEN: 19.0,
    ST_VERREIST: 15.0,
}

# Stufe -> Preset des Tado X Proxy (Stufen ohne Preset werden als Temperatur gesetzt)
PROXY_PRESETS = {
    ST_KOMFORT: "comfort",
    ST_ECO: "eco",
    ST_VERREIST: "away",
}
# Stufe -> Merkmal im entity_id der Preset-Zahl am Proxy
PROXY_NUMBER_KEYS = {
    ST_KOMFORT: ("komfort", "comfort"),
    ST_ECO: ("eco",),
    ST_VERREIST: ("abwesend", "away"),
}

# Schalter
SW_AKTIV = "aktiv"
SW_HOMEOFFICE = "homeoffice"
SW_FREI = "frei"
SW_VERREIST = "verreist"
SWITCHES = {
    SW_AKTIV: ("Heizplan", "mdi:calendar-clock"),
    SW_HOMEOFFICE: ("Homeoffice heute", "mdi:laptop"),
    SW_FREI: ("Frei / zu Hause", "mdi:beach"),
    SW_VERREIST: ("Verreist", "mdi:airplane"),
}

DEFAULT_SCHEDULE = {
    TT_BUERO: [["06:00", ST_KOMFORT], ["08:00", ST_ECO], ["16:00", ST_KOMFORT], ["22:30", ST_NACHT]],
    TT_HOMEOFFICE: [["06:45", ST_KOMFORT], ["22:30", ST_NACHT]],
    TT_WOCHENENDE: [["07:30", ST_KOMFORT], ["23:00", ST_NACHT]],
}

SIGNAL_UPDATE = f"{DOMAIN}_update"
