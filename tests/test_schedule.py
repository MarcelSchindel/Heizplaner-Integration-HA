"""Tests der reinen Plan-Logik (ohne HA)."""
import importlib.util, sys, types
from datetime import date
from pathlib import Path

base = Path(__file__).parent.parent / "custom_components" / "heizplaner"
pkg = types.ModuleType("hp"); pkg.__path__ = [str(base)]; sys.modules["hp"] = pkg
for name in ("const", "schedule"):
    spec = importlib.util.spec_from_file_location(f"hp.{name}", base / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[f"hp.{name}"] = mod; spec.loader.exec_module(mod)
S = sys.modules["hp.schedule"]
import pytest

WZ_BUERO = [["06:00","komfort"],["07:15","eco"],["16:00","komfort"],["22:30","nacht"]]
WE = [["07:30","komfort"],["23:00","nacht"]]

def test_points_sorted_validated():
    assert S.normalize_points([["16:00","komfort"],["6:00","eco"]]) == [["06:00","eco"],["16:00","komfort"]]
    for bad in ([], [["25:00","eco"]], [["06:00","warm"]], [["06:00","eco"],["06:00","komfort"]]):
        with pytest.raises(S.PlanError): S.normalize_points(bad)

def test_stufe_during_day():
    ps = S.stufe_at(WZ_BUERO, WE, 12*60)
    assert (ps.stufe, ps.since, ps.next_time, ps.next_stufe) == ("eco","07:15","16:00","komfort")

def test_before_first_point_uses_yesterday():
    ps = S.stufe_at(WZ_BUERO, [["07:30","komfort"],["23:00","eco"]], 3*60)
    assert ps.stufe == "eco" and ps.since is None and ps.next_time == "06:00"

def test_after_last_point():
    ps = S.stufe_at(WZ_BUERO, WE, 23*60)
    assert ps.stufe == "nacht" and ps.next_time is None

def test_skip_same_stufe_switch():
    ps = S.stufe_at([["06:00","komfort"],["12:00","komfort"],["20:00","eco"]], None, 7*60)
    assert ps.next_time == "20:00" and ps.next_stufe == "eco"

def test_daytypes():
    b, h = ["mon","tue","wed"], ["thu","fri"]
    mon, thu, sat = date(2026,11,23), date(2026,11,26), date(2026,11,28)
    assert S.base_daytype(mon,b,h,None).daytype == "buero"
    assert S.base_daytype(thu,b,h,None).daytype == "homeoffice"
    assert S.base_daytype(sat,b,h,None).daytype == "wochenende"
    hol = S.base_daytype(mon,b,h,"1. Weihnachtstag")
    assert hol.daytype == "wochenende" and hol.reason == "feiertag"
    base = S.base_daytype(mon,b,h,None)
    assert S.effective_daytype(base, frei=True, homeoffice=False).reason == "frei"
    assert S.effective_daytype(base, frei=False, homeoffice=True).daytype == "homeoffice"
    assert S.effective_daytype(S.base_daytype(thu,b,h,None), frei=False, homeoffice=True).daytype == "homeoffice"

def test_room_plan_fills_defaults():
    from hp.const import DEFAULT_SCHEDULE
    p = S.normalize_room_plan({"buero": WZ_BUERO, "homeoffice": "kaputt"}, DEFAULT_SCHEDULE)
    assert p["buero"] == WZ_BUERO and p["homeoffice"] == DEFAULT_SCHEDULE["homeoffice"]
