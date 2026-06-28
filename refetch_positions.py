"""Re-fetch saved sessions so their telemetry includes X/Y track position.

The X/Y position merge was added to ``data_loader._fetch_telemetry`` after most
caches were first built, so older caches have speed/throttle/brake/gear but no
track coordinates — which makes the racing-line view come up empty for those
events. This rebuilds the per-session Parquet caches in place (force_reload),
pulling position data from FastF1's raw cache (or the network if not cached).

Usage
-----
    python refetch_positions.py            # only sessions missing X/Y (default)
    python refetch_positions.py --all      # force-rebuild every cached session
"""
import sys
import warnings

warnings.filterwarnings("ignore")

import pyarrow.parquet as pq
import data_loader as dl

force_all = "--all" in sys.argv


def has_xy(key: str) -> bool:
    try:
        cols = pq.ParquetFile(dl._cache_paths(key)["telemetry"]).schema.names
        return "X" in cols and "Y" in cols
    except Exception:
        return False


def main() -> int:
    sessions = dl.list_cached_sessions()
    todo = [s for s in sessions if force_all or not has_xy(s["key"])]
    print(f"{len(sessions)} cached session(s); {len(todo)} to re-fetch"
          f"{' (--all)' if force_all else ' (missing X/Y)'}\n", flush=True)

    ok, fail = [], []
    for i, s in enumerate(todo, 1):
        season, meeting, session = str(s["season"]), str(s["meeting"]), str(s["session"])
        print(f"[{i}/{len(todo)}] {s['key']} …", flush=True)
        try:
            out = dl.load_session(season, meeting, session, force_reload=True)
            tel = out["telemetry"]
            frac = float(tel["X"].notna().mean()) if "X" in tel.columns else 0.0
            if frac > 0:
                ok.append(s["key"])
                print(f"    OK   X/Y on {frac:.1%} of {len(tel):,} rows", flush=True)
            else:
                fail.append((s["key"], "no X/Y after fetch (position data unavailable)"))
                print("    WARN no X/Y after fetch", flush=True)
        except Exception as exc:                       # noqa: BLE001 — report & continue
            fail.append((s["key"], str(exc)))
            print(f"    FAILED: {exc}", flush=True)

    print(f"\nDone. {len(ok)} ok, {len(fail)} failed/empty.")
    for key, why in fail:
        print(f"  ✗ {key} — {why}")
    return 0 if not fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
