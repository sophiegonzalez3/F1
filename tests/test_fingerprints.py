"""TELEMETRY tab style fingerprint + throttle-application cards follow the
Best Lap Leaderboard selection (tabs/fingerprints.py).

Pinned:
1. two or more ticked laps → exactly those drivers, in selection order;
2. zero or one ticked lap → VER vs LEC (the leaderboard opens with one lap
   ticked, so this is also what the tab first shows);
3. VER or LEC missing from the loaded data → topped up from the fastest;
4. a ticked driver without fingerprint data is reported, not drawn;
5. every drawn driver gets a radar silhouette and a throttle curve, with
   distinct dashes so teammates (same team colour) stay apart.
"""
import tabs.fingerprints as fp


def _store(drivers):
    metrics = {d: {"team": "McLaren", "curve": [float(i)] * len(fp._RAMP_GRID),
                   "n_brake_events": 12, "peak_brake_g": 4.5, "brake_share": 15.0,
                   "coast_share": 3.0, "full_share": 60.0, "partial_share": 22.0,
                   "ramp_s": 1.1, "lap_s": 90.0 + i}
               for i, d in enumerate(drivers)}
    pct = {d: {t: 50.0 for t in fp._TRAITS} for d in drivers}
    return {"metrics": metrics, "pct": pct, "order": list(drivers)}


ROWS = [{"Driver": d} for d in ("NOR", "PIA", "VER", "LEC", "HAM")]


def test_two_or_more_ticked_laps_are_shown_in_order():
    st = _store(["NOR", "PIA", "VER", "LEC", "HAM"])
    drivers, missing, default = fp._pick_drivers([4, 0, 1], ROWS, st)
    assert drivers == ["HAM", "NOR", "PIA"] and not default and missing == []


def test_zero_or_one_ticked_falls_back_to_ver_vs_lec():
    st = _store(["NOR", "PIA", "VER", "LEC", "HAM"])
    for sel in ([], None, [0]):
        drivers, _missing, default = fp._pick_drivers(sel, ROWS, st)
        assert drivers == ["VER", "LEC"] and default


def test_default_tops_up_from_fastest_when_ver_or_lec_absent():
    st = _store(["NOR", "PIA", "LEC"])
    drivers, _m, default = fp._pick_drivers([], ROWS, st)
    assert drivers == ["LEC", "NOR"] and default


def test_ticked_driver_without_fingerprint_is_reported():
    st = _store(["NOR", "PIA", "VER", "LEC"])          # no HAM metrics
    drivers, missing, default = fp._pick_drivers([0, 4], ROWS, st)
    assert missing == ["HAM"] and default and drivers == ["VER", "LEC"]
    drivers, missing, default = fp._pick_drivers([0, 1, 4], ROWS, st)
    assert drivers == ["NOR", "PIA"] and missing == ["HAM"] and not default


def test_figures_draw_every_selected_driver_with_distinct_dashes():
    st = _store(["NOR", "PIA", "VER"])
    radar = fp._radar_fig(st, ["NOR", "PIA", "VER"])
    ramp = fp._ramp_fig(st, ["NOR", "PIA", "VER"])
    r_names = [t.name for t in radar.data if t.name != "field median"]
    c_names = [t.name for t in ramp.data if t.name != "field average"]
    assert r_names == c_names == ["NOR", "PIA", "VER"]
    dashes = [t.line.dash for t in ramp.data if t.name in c_names]
    assert len(set(dashes)) == 3


def test_callback_returns_figures_and_captions():
    st = _store(["NOR", "PIA", "VER", "LEC", "HAM"])
    radar, ramp, cap, cap2 = fp._update_fingerprint([1, 3], ROWS, st)
    assert [t.name for t in ramp.data if t.name != "field average"] == ["PIA", "LEC"]
    assert cap is cap2 and "PIA · LEC" in str(cap)
