"""
Track scene builder — georeferenced 3D track geometry for the quali replay.

Pipeline (offline, once per season+circuit, cached to data/track_scenes/):

  1. FastF1 track map (tabs.track.get_track_map) gives the racing line in
     FastF1 local coordinates (0.1 m units, arbitrary rotation/origin).
  2. Overpass gives every highway=raceway way near the circuit (OSM asphalt
     centerlines + per-way width tags).
  3. A similarity transform (rotation grid search + trimmed ICP; scale is
     known ≈1 because FastF1 units are 0.1 m) georeferences the racing line
     onto the OSM cloud — residuals are the racing-line-vs-centerline offset
     (median ~2 m when the fit is good).
  4. The racing line is snapped onto the OSM centerlines → the *asphalt
     centre* ordered along the lap, with real track width per point.
  5. A country DTM provider (lidar where available) samples elevation across
     the track width at each point → true slope AND camber/banking.
     Fallback: telemetry z along the centerline, zero camber.

The baked scene is a compact JSON (metres, rotated to the same display
orientation as the 2D track map) that assets/quali3d.js turns into a
Three.js ribbon mesh. The `geo` block stores the fitted transform so later
phases (OSM buildings, barriers) can project any lat/lon feature into the
same frame.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)

SCENES_DIR = Path("data/track_scenes")
_SCENE_VERSION = 4
_STEP = 2.0            # centerline resample step (m)
_DEFAULT_HALFW = 6.0   # half track width when OSM has no width tag (m)

# Surroundings (phase 2): everything is baked monochrome-agnostic — the JS
# renders it in neutral greys so the coloured track/cars stay the focus.
_BLDG_MAX_DIST = 300.0    # keep buildings within this distance of the track (m)
_WALL_MAX_DIST = 150.0    # barriers/walls
_TREE_MAX_DIST = 250.0    # trees
_BLDG_CAP = 4500          # hard caps keep the payload and draw calls sane
_TREE_CAP = 4000
_TERRAIN_STEP = 8.0       # terrain heightmap resolution (m)
_TERRAIN_MARGIN = 300.0   # terrain extends this far beyond the track bbox

# Circuit seed coordinates for the Overpass query (approximate track centre)
# and the DTM provider to use. Keyed by substrings of the FastF1 event name.
#   dtm: "ahn"  — Dutch national lidar, 0.5 m (PDOK WCS, CC0)
#        None   — fallback: telemetry z along centerline, zero camber
CIRCUITS: dict[str, dict] = {
    "australian":     {"latlon": (-37.8497, 144.9680), "dtm": None},
    "chinese":        {"latlon": (31.3389, 121.2200),  "dtm": None},
    "japanese":       {"latlon": (34.8431, 136.5411),  "dtm": None},
    "bahrain":        {"latlon": (26.0325, 50.5106),   "dtm": None},
    "saudi":          {"latlon": (21.6319, 39.1044),   "dtm": None},
    "miami":          {"latlon": (25.9581, -80.2389),  "dtm": None},
    "emilia":         {"latlon": (44.3439, 11.7167),   "dtm": None},
    "monaco":         {"latlon": (43.7347, 7.4206),    "dtm": None},
    "canadian":       {"latlon": (45.5000, -73.5228),  "dtm": None},
    "spanish":        {"latlon": (41.5700, 2.2611),    "dtm": "ign_es"},
    "barcelona":      {"latlon": (41.5700, 2.2611),    "dtm": "ign_es"},
    "austrian":       {"latlon": (47.2197, 14.7647),   "dtm": None},
    "british":        {"latlon": (52.0786, -1.0169),   "dtm": None},
    "belgian":        {"latlon": (50.4372, 5.9714),    "dtm": None},
    "hungarian":      {"latlon": (47.5789, 19.2486),   "dtm": None},
    "dutch":          {"latlon": (52.3888, 4.5409),    "dtm": "ahn"},
    "italian":        {"latlon": (45.6156, 9.2811),    "dtm": None},
    "madrid":         {"latlon": (40.4650, -3.6167),   "dtm": "ign_es"},
    "azerbaijan":     {"latlon": (40.3725, 49.8533),   "dtm": None},
    "singapore":      {"latlon": (1.2914, 103.8642),   "dtm": None},
    "united_states":  {"latlon": (30.1328, -97.6411),  "dtm": None},
    "mexico":         {"latlon": (19.4042, -99.0907),  "dtm": None},
    "paulo":          {"latlon": (-23.7036, -46.6997), "dtm": None},
    "vegas":          {"latlon": (36.1147, -115.1728), "dtm": None},
    "qatar":          {"latlon": (25.4900, 51.4542),   "dtm": None},
    "abu_dhabi":      {"latlon": (24.4672, 54.6031),   "dtm": None},
}


def _slug(meeting: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(meeting)).strip("_").lower()


def _circuit_conf(meeting: str) -> dict | None:
    s = _slug(meeting)
    for key, conf in CIRCUITS.items():
        if key in s:
            return conf
    return None


def scene_cache_path(season: int, meeting: str) -> Path:
    return SCENES_DIR / f"{season}_{_slug(meeting)}_scene_v{_SCENE_VERSION}.json.gz"


def cached_scene(season: int, meeting: str) -> dict | None:
    path = scene_cache_path(season, meeting)
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return None


# ─────────────────────────────────────────────────────────────
# OSM (Overpass)
# ─────────────────────────────────────────────────────────────

_OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]


def _overpass(q: str, timeout: int = 60) -> dict:
    last_exc = None
    for url in _OVERPASS_MIRRORS:
        try:
            req = urllib.request.Request(
                url, data=urllib.parse.urlencode({"data": q}).encode(),
                headers={"User-Agent": "f1-dash-track-scene/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as exc:               # busy mirror → try the next
            logger.warning("Overpass mirror %s failed: %s", url, exc)
            last_exc = exc
    raise last_exc


def _way_length_m(way: dict) -> float:
    g = np.array([(p["lat"], p["lon"]) for p in way["geometry"]])
    return float(np.hypot(np.diff(g[:, 0]) * 111000,
                          np.diff(g[:, 1]) * 76000).sum())


def _fetch_osm_track(meeting: str, lat: float, lon: float,
                     lap_len: float | None = None,
                     radius: int = 3000) -> list[dict]:
    """Track centerline ways near the circuit seed.

    Preferred source: the OSM circuit *relation* whose member length matches
    the telemetry lap length — venues carry many raceway-tagged layouts
    (Silverstone: GP + International + National + Stowe + a proving ground,
    20 km of ways for a 5.9 km lap) that poison the georef fit. Members are
    swapped for their tagged way (width!) when one exists; street-circuit
    members (Monaco) keep their bare geometry. Fallback: all raceway ways,
    then relation members regardless of length. Cached for offline rebuilds."""
    cache = SCENES_DIR / "osm" / f"{_slug(meeting)}_track.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
    else:
        q = (f'[out:json][timeout:90];'
             f'(way["highway"="raceway"](around:{radius},{lat},{lon});'
             f'relation["type"="circuit"](around:{radius},{lat},{lon});'
             f'relation["sport"="motor"]["type"="circuit"]'
             f'(around:{radius},{lat},{lon}););'
             f'out geom;')
        data = _overpass(q)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")

    elements = data.get("elements", [])
    ways = [e for e in elements if e["type"] == "way"
            and len(e.get("geometry", [])) >= 2]
    by_id = {w["id"]: w for w in ways}

    rels = []
    for rel in elements:
        if rel["type"] != "relation":
            continue
        members = [m for m in rel.get("members", [])
                   if m.get("type") == "way" and len(m.get("geometry") or []) >= 2]
        if not members:
            continue
        total = sum(_way_length_m(m) for m in members)
        rels.append((rel, members, total))

    def _member_ways(members):
        return [by_id.get(m.get("ref"),
                          {"id": m.get("ref"), "tags": {},
                           "geometry": m["geometry"]})
                for m in members]

    # 1) relation matching the lap length → clean, layout-exact cloud.
    #    Among length-plausible candidates prefer a "grand prix" name:
    #    Silverstone International (5821 m) beats Grand Prix (5891 m) on
    #    pure distance to a 5829 m lap, but it's the wrong layout.
    if lap_len and rels:
        ok = [r for r in rels if abs(r[2] - lap_len) / lap_len < 0.3]
        # "grand prix"-named relations often double-count the loop corridor
        # (Silverstone GP: 13.2 km of members for a 5.9 km lap) yet still fit
        # far better than a same-length sister layout — allow up to 2.6× lap
        gp = [r for r in rels
              if "grand prix" in r[0].get("tags", {}).get("name", "").lower()
              and 0.7 <= r[2] / lap_len <= 2.6]
        best = (min(gp, key=lambda r: abs(r[2] - lap_len)) if gp
                else (min(ok, key=lambda r: abs(r[2] - lap_len)) if ok else None))
        if best is not None:
            logger.info("track ways from relation %r (%d m vs lap %d m)",
                        best[0].get("tags", {}).get("name", best[0]["id"]),
                        int(best[2]), int(lap_len))
            return _member_ways(best[1])

    # 2) plain raceway ways when they plausibly cover a lap
    covered = sum(_way_length_m(w) for w in ways if not _is_pit_way(w))
    if covered >= 2500:
        return ways

    # 3) street circuit without a length match: any relation is better
    #    than nothing
    if rels:
        return ways + _member_ways(rels[0][1])
    return ways


def _fetch_osm_surround(meeting: str, lat: float, lon: float,
                        radius: int = 1600) -> dict:
    """Buildings, barriers and trees around the circuit (one Overpass call,
    cached). Street circuits (Monaco) return thousands of buildings — the
    distance filters and caps are applied later, against the fitted track."""
    cache = SCENES_DIR / "osm" / f"{_slug(meeting)}_surround.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    q = (f'[out:json][timeout:180];'
         f'(way["building"](around:{radius},{lat},{lon});'
         f'way["barrier"](around:{radius},{lat},{lon});'
         f'node["natural"="tree"](around:{radius},{lat},{lon}););'
         f'out geom;')
    data = _overpass(q, timeout=240)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


def _is_pit_way(way: dict) -> bool:
    tags = way.get("tags", {})
    name = (tags.get("name", "") + " " + tags.get("description", "")).lower()
    return ("pit" in name or "paddock" in name
            or "stands" in name             # fr: "Voie des stands"
            or tags.get("area") == "yes")   # area polygons: no usable centerline


_FOREIGN_SPORTS = {"karting", "motocross", "rc_car", "cycling", "bmx",
                   "equestrian", "greyhound_racing", "horse_racing"}
_FOREIGN_NAMES = ("karting", "rallycross", "motocross", "cross track",
                  "flat track", "junior track", "supercross", "dirt")


def _is_foreign_way(way: dict) -> bool:
    """Raceway that is NOT the car circuit: circuits share their site with
    karting / motocross / rallycross tracks (Catalunya has all three) which
    poison both the georef fit and the centerline snap."""
    tags = way.get("tags", {})
    if tags.get("sport") in _FOREIGN_SPORTS:
        return True
    name = tags.get("name", "").lower()
    return any(k in name for k in _FOREIGN_NAMES)


# ─────────────────────────────────────────────────────────────
# Local metric frame + georeferencing fit
# ─────────────────────────────────────────────────────────────

class _LocalFrame:
    """Equirectangular projection (metres) centred on the OSM cloud —
    plenty accurate over a ~5 km circuit."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = float(lat0), float(lon0)
        self.m_lat = 111132.954 - 559.822 * np.cos(2 * np.radians(lat0))
        self.m_lon = 111132.954 * np.cos(np.radians(lat0))

    def to_xy(self, lat, lon):
        return np.column_stack([(np.asarray(lon) - self.lon0) * self.m_lon,
                                (np.asarray(lat) - self.lat0) * self.m_lat])

    def to_latlon(self, xy):
        xy = np.asarray(xy, float)
        return np.column_stack([xy[:, 1] / self.m_lat + self.lat0,
                                xy[:, 0] / self.m_lon + self.lon0])


def _densify_ways(ways: list[dict], frame: _LocalFrame, step: float = 2.0
                  ) -> tuple[np.ndarray, np.ndarray]:
    """OSM ways → dense point cloud (metres) + parallel way-index array."""
    pts, widx = [], []
    for i, w in enumerate(ways):
        g = np.array([(p["lat"], p["lon"]) for p in w["geometry"]])
        xy = frame.to_xy(g[:, 0], g[:, 1])
        for a, b in zip(xy[:-1], xy[1:]):
            d = float(np.hypot(*(b - a)))
            n = max(int(d / step), 1)
            for t in np.linspace(0, 1, n, endpoint=False):
                pts.append(a + t * (b - a))
                widx.append(i)
    return np.asarray(pts), np.asarray(widx)


def _resample_by_arclength(xy: np.ndarray, step: float) -> np.ndarray:
    """Telemetry is sampled in TIME (slow corners over-weighted); resample by
    arc length so the georef fit and its centroid are unbiased."""
    seg = np.hypot(*np.diff(xy, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    si = np.arange(0.0, s[-1], step)
    return np.column_stack([np.interp(si, s, xy[:, 0]),
                            np.interp(si, s, xy[:, 1])])


def _rotm(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s], [s, c]])


def _fit_similarity(tel_m: np.ndarray, osm_xy: np.ndarray) -> dict:
    """Rotation grid search + trimmed rigid ICP: telemetry metres → OSM local
    metres. The scale is LOCKED to 1.0 — FastF1 units are exactly 0.1 m, and a
    free scale lets ICP collapse into dense clutter (Monaco: scale drifted to
    0.11 before locking; locked it converges to 1.4 m median from a 70 m-off
    init). Returns {R, s, t, mu, median, p95}: apply as p = s·(x−mu)·Rᵀ + t."""
    tree = cKDTree(osm_xy)
    mu = tel_m.mean(axis=0)
    src = tel_m - mu
    target_c = osm_xy.mean(axis=0)

    # score every rotation, then ICP from the best few mutually-distant ones —
    # near-symmetric circuits (Red Bull Ring) trap a single-start ICP in the
    # wrong local minimum depending on tiny changes in the target cloud
    degs = np.arange(0.0, 360.0, 1.0)
    scores = np.empty(len(degs))
    for i, deg in enumerate(degs):
        p = src @ _rotm(np.radians(deg)).T + target_c
        d, _ = tree.query(p)
        scores[i] = float(np.mean(np.sort(d)[: int(len(d) * 0.8)]))
    starts = []
    for i in np.argsort(scores):
        if all(min(abs(degs[i] - s), 360 - abs(degs[i] - s)) >= 25.0
               for s in starts):
            starts.append(float(degs[i]))
        if len(starts) == 5:
            break

    def _icp(deg0: float):
        R = _rotm(np.radians(deg0))
        t = target_c
        for _ in range(60):
            p = src @ R.T + t
            d, idx = tree.query(p)
            keep = d < np.percentile(d, 75)
            A, B = src[keep], osm_xy[idx[keep]]
            Am, Bm = A.mean(axis=0), B.mean(axis=0)
            U, _S, Vt = np.linalg.svd((A - Am).T @ (B - Bm))
            D = np.diag([1.0, np.sign(np.linalg.det(Vt.T @ U.T))])
            R = Vt.T @ D @ U.T
            t = Bm - Am @ R.T
        p = src @ R.T + t
        d, _ = tree.query(p)
        return float(np.median(d)), float(np.percentile(d, 95)), R, t

    med, p95, R, t = min((_icp(s) for s in starts), key=lambda r: r[0])
    return {"R": R, "s": 1.0, "t": t, "mu": mu, "median": med, "p95": p95}


# ─────────────────────────────────────────────────────────────
# DTM providers
# ─────────────────────────────────────────────────────────────

class _RasterDtm:
    """Georeferenced elevation raster with bilinear sampling at WGS84 points.
    Subclasses fetch/cache the raster; `camber` says whether the grid is fine
    and precise enough for cross-track slope (banking) to be meaningful."""

    name = "raster"
    camber = False
    crs = "EPSG:4326"

    def _load(self, tif: Path) -> None:
        import rasterio
        self._ds = rasterio.open(tif)
        self._arr = self._ds.read(1)
        self._nodata = self._ds.nodata

    def sample(self, lats, lons) -> np.ndarray:
        """Bilinear elevation (m) at WGS84 points; NaN outside/nodata."""
        lats = np.asarray(lats, float)
        lons = np.asarray(lons, float)
        if self.crs != "EPSG:4326":
            from rasterio.warp import transform as rio_transform
            xs, ys = rio_transform("EPSG:4326", self.crs,
                                   lons.tolist(), lats.tolist())
            xs, ys = np.asarray(xs), np.asarray(ys)
        else:
            xs, ys = lons, lats
        gt, arr = self._ds.transform, self._arr
        cols = (xs - gt.c) / gt.a
        rows = (ys - gt.f) / gt.e
        c0 = np.clip(np.floor(cols).astype(int), 0, arr.shape[1] - 2)
        r0 = np.clip(np.floor(rows).astype(int), 0, arr.shape[0] - 2)
        fc, fr = cols - c0, rows - r0
        q = [arr[r0, c0], arr[r0, c0 + 1], arr[r0 + 1, c0], arr[r0 + 1, c0 + 1]]
        v = (q[0] * (1 - fr) * (1 - fc) + q[1] * (1 - fr) * fc
             + q[2] * fr * (1 - fc) + q[3] * fr * fc)
        bad = np.zeros(v.shape, bool)
        if self._nodata is not None:
            for a in q:
                bad |= (a == self._nodata)
        bad |= (cols < 0) | (rows < 0) | (cols > arr.shape[1] - 1) | (rows > arr.shape[0] - 1)
        return np.where(bad, np.nan, v.astype(float))


class AhnDtm(_RasterDtm):
    """AHN4 0.5 m DTM (Dutch national lidar) via the PDOK WCS. CC0.
    Fine enough for true camber/banking. Cached on disk (~10 MB GeoTIFF)."""

    name = "AHN4 lidar 0.5 m (PDOK, CC0)"
    camber = True
    crs = "EPSG:28992"
    _WCS = ("https://service.pdok.nl/rws/ahn/wcs/v1_0?service=WCS"
            "&version=1.0.0&request=GetCoverage&coverage=dtm_05m"
            "&crs=EPSG:28992&format=GEOTIFF")

    def __init__(self, meeting: str, lats: np.ndarray, lons: np.ndarray):
        from rasterio.warp import transform as rio_transform
        tif = SCENES_DIR / "dtm" / f"{_slug(meeting)}_ahn_dtm05.tif"
        if not tif.exists():
            xs, ys = rio_transform("EPSG:4326", "EPSG:28992",
                                   [float(lons.min()), float(lons.max())],
                                   [float(lats.min()), float(lats.max())])
            pad = 80.0
            x0 = np.floor((min(xs) - pad) * 2) / 2
            y0 = np.floor((min(ys) - pad) * 2) / 2
            x1 = np.ceil((max(xs) + pad) * 2) / 2
            y1 = np.ceil((max(ys) + pad) * 2) / 2
            w, h = int((x1 - x0) / 0.5), int((y1 - y0) / 0.5)
            url = f"{self._WCS}&bbox={x0},{y0},{x1},{y1}&width={w}&height={h}"
            logger.info("AHN WCS fetch %dx%d px for %s", w, h, meeting)
            req = urllib.request.Request(
                url, headers={"User-Agent": "f1-dash-track-scene/1.0"})
            tif.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(req, timeout=600) as r:
                tif.write_bytes(r.read())
        self._load(tif)


class IgnEsDtm(_RasterDtm):
    """Spanish IGN PNOA-lidar MDT, 5 m grid via the INSPIRE WCS 2.0
    (Elevacion4258_5 — ETRS89 ≈ WGS84 at our accuracy). Values are metre-
    quantized → good for elevation/terrain, too coarse for camber."""

    name = "IGN PNOA lidar MDT 5 m (Spain)"
    camber = False
    _WCS = ("https://servicios.idee.es/wcs-inspire/mdt?SERVICE=WCS"
            "&VERSION=2.0.1&REQUEST=GetCoverage&COVERAGEID=Elevacion4258_5"
            "&FORMAT=image/tiff")

    def __init__(self, meeting: str, lats: np.ndarray, lons: np.ndarray):
        tif = SCENES_DIR / "dtm" / f"{_slug(meeting)}_ign_mdt5.tif"
        if not tif.exists():
            pad = 0.005          # ~500 m
            la0, la1 = float(lats.min()) - pad, float(lats.max()) + pad
            lo0, lo1 = float(lons.min()) - pad, float(lons.max()) + pad
            url = (f"{self._WCS}&SUBSET=lat({la0:.5f},{la1:.5f})"
                   f"&SUBSET=long({lo0:.5f},{lo1:.5f})")
            logger.info("IGN WCS fetch for %s", meeting)
            req = urllib.request.Request(
                url, headers={"User-Agent": "f1-dash-track-scene/1.0"})
            tif.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(req, timeout=600) as r:
                tif.write_bytes(r.read())
        self._load(tif)


class CopernicusDtm(_RasterDtm):
    """Copernicus GLO-30 DSM (global, ~30 m) from the AWS open-data bucket —
    windowed remote read of the circuit surroundings, cached as a small
    GeoTIFF. Background terrain only: it is a *surface* model (canopy!), so
    never used for the track ribbon itself."""

    name = "Copernicus GLO-30 (terrain)"
    camber = False

    def __init__(self, meeting: str, lats: np.ndarray, lons: np.ndarray):
        import rasterio
        from rasterio.windows import from_bounds
        tif = SCENES_DIR / "dtm" / f"{_slug(meeting)}_cop30.tif"
        if not tif.exists():
            pad = 0.008          # ~800 m
            la0, la1 = float(lats.min()) - pad, float(lats.max()) + pad
            lo0, lo1 = float(lons.min()) - pad, float(lons.max()) + pad
            clat, clon = (la0 + la1) / 2, (lo0 + lo1) / 2
            ns = "N" if clat >= 0 else "S"
            ew = "E" if clon >= 0 else "W"
            t = (f"Copernicus_DSM_COG_10_{ns}{abs(int(np.floor(clat))):02d}_00"
                 f"_{ew}{abs(int(np.floor(clon))):03d}_00_DEM")
            url = f"/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/{t}/{t}.tif"
            logger.info("Copernicus GLO-30 fetch %s for %s", t, meeting)
            src = rasterio.open(url)
            win = from_bounds(lo0, la0, lo1, la1, src.transform)
            arr = src.read(1, window=win)
            tr = src.window_transform(win)
            tif.parent.mkdir(parents=True, exist_ok=True)
            prof = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                        count=1, dtype=str(arr.dtype), crs=src.crs,
                        transform=tr, nodata=src.nodata)
            with rasterio.open(tif, "w", **prof) as dst:
                dst.write(arr, 1)
        self._load(tif)


_DTM_PROVIDERS = {"ahn": AhnDtm, "ign_es": IgnEsDtm}


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _despike(a: np.ndarray, win: int = 25, thresh: float = 2.0) -> np.ndarray:
    """Replace short spikes with the local median. FastF1's Z channel has
    isolated multi-metre glitches (Suzuka: a 6.4 m step at 130R) that survive
    plain smoothing; real elevation deviates from a 50 m median slowly, so a
    2 m threshold separates the two."""
    from scipy.ndimage import median_filter
    a = np.asarray(a, float)
    if not np.isfinite(a).any():
        return a
    med = median_filter(np.nan_to_num(a, nan=float(np.nanmedian(a))),
                        size=win, mode="wrap")
    return np.where(np.abs(a - med) > thresh, med, a)


def _smooth(a: np.ndarray, win: int) -> np.ndarray:
    """Centred moving average that tolerates NaNs (interpolated first)."""
    a = np.asarray(a, float)
    if np.isnan(a).any():
        idx = np.arange(len(a))
        ok = np.isfinite(a)
        if ok.sum() < 2:
            return np.zeros_like(a)
        a = np.interp(idx, idx[ok], a[ok])
    if win <= 1 or len(a) < win:
        return a
    k = np.ones(win) / win
    pad = win // 2
    ap = np.concatenate([a[:pad][::-1], a, a[-pad:][::-1]])
    return np.convolve(ap, k, mode="valid")[: len(a)]


def _rotate(x, y, angle_rad):
    ca, sa = np.cos(angle_rad), np.sin(angle_rad)
    return x * ca - y * sa, x * sa + y * ca


# Lateral sample offsets across the half-width (fractions of hw).
_XSEC = np.array([-1.0, -0.5, 0.0, 0.5, 1.0])


def _parse_height(tags: dict, default: float) -> float:
    """Building/barrier height from OSM tags (height in m, or levels·3.2)."""
    for key in ("height", "building:height"):
        if key in tags:
            m = re.match(r"\s*([\d.]+)", str(tags[key]))
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
    for key in ("building:levels", "levels"):
        if key in tags:
            try:
                return float(tags[key]) * 3.2 + 1.5
            except (ValueError, TypeError):
                pass
    return default


_BARRIER_H = {"wall": 2.0, "city_wall": 4.0, "retaining_wall": 2.5,
              "guard_rail": 0.9, "fence": 1.8, "hedge": 1.5}


def _build_surround(meeting: str, conf: dict, frame: "_LocalFrame", fit: dict,
                    ang: float, cx: np.ndarray, cy: np.ndarray,
                    zc: np.ndarray, hw: np.ndarray, datum: float,
                    dtm) -> dict | None:
    """Buildings / barriers / trees / terrain in the scene display frame.
    Purely geometric — the viewer renders all of it in neutral greys."""
    try:
        raw = _fetch_osm_surround(meeting, *conf["latlon"])
    except Exception as exc:
        logger.warning("surroundings unavailable for %s: %s", meeting, exc)
        return None

    ttree = cKDTree(np.column_stack([cx, cy]))

    def ll_to_scene(ll: np.ndarray) -> np.ndarray:
        xy = frame.to_xy(ll[:, 0], ll[:, 1])
        tel = ((xy - fit["t"]) @ fit["R"]) / fit["s"] + fit["mu"]
        x, y = _rotate(tel[:, 0], tel[:, 1], ang)
        return np.column_stack([x, y])

    def scene_to_ll(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        ux, uy = _rotate(np.asarray(x), np.asarray(y), -ang)
        tel = np.column_stack([ux, uy])
        loc = fit["s"] * ((tel - fit["mu"]) @ fit["R"].T) + fit["t"]
        return frame.to_latlon(loc)

    # ── background terrain source: national DTM if present, else Copernicus
    #    GLO-30 (global DSM), vertically aligned to the track datum via the
    #    centerline (its absolute origin differs from telemetry z) ──
    cop, cop_off = None, 0.0
    try:
        llc = scene_to_ll(cx, cy)
        cop = CopernicusDtm(meeting, llc[:, 0], llc[:, 1])
        zs = cop.sample(llc[:, 0], llc[:, 1])
        if np.isfinite(zs).sum() > len(zs) * 0.5:
            cop_off = float(np.nanmedian(zs - zc))
        else:
            cop = None
    except Exception as exc:
        logger.warning("Copernicus terrain unavailable for %s: %s", meeting, exc)
        cop = None

    def terrain_z(ll: np.ndarray) -> np.ndarray:
        """Best background elevation (track datum): national DTM first,
        Copernicus where it has no coverage. NaN when neither knows."""
        z = np.full(len(ll), np.nan)
        if dtm is not None:
            z = dtm.sample(ll[:, 0], ll[:, 1]) - datum
        if cop is not None:
            zcop = cop.sample(ll[:, 0], ll[:, 1]) - cop_off
            z = np.where(np.isfinite(z), z, zcop)
        return z

    def ground(pts_scene: np.ndarray, ll: np.ndarray) -> np.ndarray:
        """Ground elevation for features: right at the track use the track's
        own elevation (that's where wall-proximity must look right); blend to
        the national DTM with distance where one exists. Copernicus is a
        *surface* model (canopy, buildings) — never trusted for feature
        placement, only for the backdrop heightmap."""
        d, idx = ttree.query(pts_scene)
        near = zc[idx]
        if dtm is None:
            return near
        zt = dtm.sample(ll[:, 0], ll[:, 1]) - datum
        w = np.clip((d - 15.0) / 40.0, 0.0, 1.0)
        return np.where(np.isfinite(zt), (1 - w) * near + w * zt, near)

    buildings, walls, trees = [], [], []
    for e in raw.get("elements", []):
        tags = e.get("tags", {})
        if e["type"] == "way" and "building" in tags:
            g = e.get("geometry") or []
            if len(g) < 3:
                continue
            ll = np.array([(p["lat"], p["lon"]) for p in g])
            if np.allclose(ll[0], ll[-1]):
                ll = ll[:-1]
            if len(ll) < 3:
                continue
            pts = ll_to_scene(ll)
            ctr = pts.mean(axis=0, keepdims=True)
            d, _ = ttree.query(ctr)
            if d[0] > _BLDG_MAX_DIST:
                continue
            z0 = float(ground(ctr, ll.mean(axis=0, keepdims=True))[0])
            buildings.append({
                "d": float(d[0]),
                "p": np.round(pts, 1).tolist(),
                "h": round(_parse_height(tags, 6.0), 1),
                "z": round(z0 - 0.3, 1),
            })
        elif e["type"] == "way" and "barrier" in tags:
            g = e.get("geometry") or []
            if len(g) < 2:
                continue
            ll = np.array([(p["lat"], p["lon"]) for p in g])
            pts = ll_to_scene(ll)
            d, _ = ttree.query(pts)
            if d.min() > _WALL_MAX_DIST:
                continue
            h = _parse_height(tags, _BARRIER_H.get(tags.get("barrier"), 1.2))
            walls.append({
                "p": np.round(pts, 1).tolist(),
                "h": round(min(h, 6.0), 1),
                "z": np.round(ground(pts, ll) - 0.2, 1).tolist(),
            })
        elif e["type"] == "node" and tags.get("natural") == "tree":
            ll = np.array([[e["lat"], e["lon"]]])
            pt = ll_to_scene(ll)
            d, _ = ttree.query(pt)
            if d[0] > _TREE_MAX_DIST or d[0] < 8.0:
                continue
            z0 = float(ground(pt, ll)[0])
            trees.append([round(float(pt[0, 0]), 1),
                          round(float(pt[0, 1]), 1), round(z0, 1)])

    # nearest buildings first, then cap (Monaco has thousands)
    buildings.sort(key=lambda b: b["d"])
    buildings = buildings[:_BLDG_CAP]
    for b in buildings:
        del b["d"]
    if len(trees) > _TREE_CAP:
        trees = trees[:: len(trees) // _TREE_CAP + 1]

    # terrain heightmap (dune/hill relief) — national DTM composited with
    # the Copernicus fallback, so every georeferenced circuit gets one
    terrain = None
    if dtm is not None or cop is not None:
        x0 = float(cx.min() - _TERRAIN_MARGIN)
        x1 = float(cx.max() + _TERRAIN_MARGIN)
        y0 = float(cy.min() - _TERRAIN_MARGIN)
        y1 = float(cy.max() + _TERRAIN_MARGIN)
        gx = np.arange(x0, x1, _TERRAIN_STEP)
        gy = np.arange(y0, y1, _TERRAIN_STEP)
        GX, GY = np.meshgrid(gx, gy)
        ll = scene_to_ll(GX.ravel(), GY.ravel())
        z = terrain_z(ll)
        z = np.where(np.isfinite(z), z, np.nanmin(z[np.isfinite(z)]) if
                     np.isfinite(z).any() else 0.0)
        # corridor clamp: the DSM fallback includes canopy/buildings which
        # tower over the road and swallow the cars ("mud"). Force the terrain
        # below the track surface near the ribbon; allowance grows ~45° with
        # distance so real hillsides further out survive.
        d, idx = ttree.query(np.column_stack([GX.ravel(), GY.ravel()]))
        edge = np.asarray(hw)[idx] + 9.0          # ribbon + shoulder
        lim = zc[idx] - 0.8 + np.maximum(0.0, d - edge) * 1.0
        z = np.minimum(z, lim)
        terrain = {
            "x0": round(x0, 1), "y0": round(y0, 1), "step": _TERRAIN_STEP,
            "nx": len(gx), "ny": len(gy),
            # decimeters as ints — compact after gzip
            "z": np.rint(z * 10).astype(int).tolist(),
        }

    logger.info("surround %s: %d buildings, %d walls, %d trees, terrain=%s",
                meeting, len(buildings), len(walls), len(trees),
                "yes" if terrain else "no")
    return {"buildings": buildings, "walls": walls, "trees": trees,
            "terrain": terrain}


# ─────────────────────────────────────────────────────────────
# Scene builder
# ─────────────────────────────────────────────────────────────

def build_track_scene(season: int, meeting: str, force: bool = False) -> dict | None:
    """Build (or load) the georeferenced 3D track scene for a circuit.
    Returns None only when even the telemetry fallback is impossible."""
    if not force:
        scene = cached_scene(season, meeting)
        if scene is not None:
            return scene

    from tabs.track import get_track_map          # lazy: heavy import chain
    tm = get_track_map(season, meeting, "Q")
    if tm is None or tm["line"].empty:
        return None
    line = tm["line"]
    rotation = float(tm.get("rotation", 0.0))
    tel_m = line[["X", "Y"]].dropna().to_numpy(float) * 0.1     # metres
    tel_z = (line["z"].to_numpy(float) * 0.1
             if "z" in line.columns else np.full(len(tel_m), np.nan))

    # arc-length resampled racing line (the lap path, ordered)
    seg = np.hypot(*np.diff(tel_m, axis=0).T)
    s_tel = np.concatenate([[0.0], np.cumsum(seg)])
    s_grid = np.arange(0.0, s_tel[-1], _STEP)
    race = np.column_stack([np.interp(s_grid, s_tel, tel_m[:, 0]),
                            np.interp(s_grid, s_tel, tel_m[:, 1])])
    race_z = (_despike(np.interp(s_grid, s_tel, tel_z))
              if np.isfinite(tel_z).sum() > len(tel_z) * 0.5
              else np.full(len(s_grid), np.nan))

    conf = _circuit_conf(meeting)
    sources = {"track": "telemetry", "dtm": "telemetry-z"}
    geo_meta = None
    center = race.copy()
    hw = np.full(len(center), _DEFAULT_HALFW)

    frame = fit = None
    if conf is not None:
        try:
            ways = _fetch_osm_track(meeting, *conf["latlon"],
                                    lap_len=float(s_tel[-1]))
            ways = [w for w in ways if not _is_foreign_way(w)]
            main_ways = [w for w in ways if not _is_pit_way(w)]
            if len(main_ways) >= 1:
                all_pts = np.array([(g["lat"], g["lon"])
                                    for w in ways for g in w["geometry"]])
                frame = _LocalFrame(all_pts[:, 0].mean(), all_pts[:, 1].mean())
                cloud, _ = _densify_ways(ways, frame)          # fit vs ALL ways
                fit = _fit_similarity(race, cloud)
                logger.info("georef %s: median %.2f m, p95 %.2f m, scale %.4f",
                            meeting, fit["median"], fit["p95"], fit["s"])
                if fit["median"] < 6.0:                        # sane fit only
                    main_cloud, main_widx = _densify_ways(main_ways, frame, step=1.0)
                    mtree = cKDTree(main_cloud)
                    fitted = fit["s"] * ((race - fit["mu"]) @ fit["R"].T) + fit["t"]
                    d, idx = mtree.query(fitted)
                    snapped = main_cloud[idx]
                    # keep the racing line where OSM is far away (mapping gaps)
                    far = d > 15.0
                    snapped[far] = fitted[far]
                    # smooth out OSM vertex kinks (10 m window)
                    snapped = np.column_stack([_smooth(snapped[:, 0], 5),
                                               _smooth(snapped[:, 1], 5)])
                    # asphalt centre back into the telemetry frame (metres)
                    center = ((snapped - fit["t"]) @ fit["R"]) / fit["s"] + fit["mu"]
                    # per-point width from the matched way's tag; relation-
                    # synthesized ways (street circuits) carry no tags — use a
                    # street-realistic default so buildings hug the edges
                    default_w = (_DEFAULT_HALFW * 2
                                 if any(w["tags"] for w in main_ways) else 10.0)
                    widths = np.full(len(center), default_w)
                    for i, wi in enumerate(main_widx[idx]):
                        try:
                            widths[i] = float(main_ways[wi]["tags"].get(
                                "width", default_w))
                        except (ValueError, TypeError):
                            pass
                    hw = np.clip(_smooth(widths, 9) / 2.0, 4.0, 13.0)
                    sources["track"] = "osm"
                    geo_meta = {
                        "lat0": frame.lat0, "lon0": frame.lon0,
                        "R": fit["R"].tolist(), "s": fit["s"],
                        "t": fit["t"].tolist(), "mu": fit["mu"].tolist(),
                        "median_m": fit["median"], "p95_m": fit["p95"],
                    }
                else:
                    logger.warning("georef fit poor for %s (median %.1f m) — "
                                   "falling back to racing line", meeting, fit["median"])
                    fit = None
        except Exception as exc:
            logger.warning("OSM/georef unavailable for %s: %s", meeting, exc)
            fit = None

    # ── tangents / normals along the asphalt centre ──
    tang = np.gradient(center, axis=0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
    dist = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(center, axis=0).T))])

    # ── kerbs from curvature: apex side of every corner tighter than ~130 m
    #    radius, zone dilated ±14 m (0 none, 1 left edge, 2 right edge) ──
    theta = np.unwrap(np.arctan2(tang[:, 1], tang[:, 0]))
    curv = _smooth(np.gradient(theta) / _STEP, 9)
    strong = (np.abs(curv) > 1.0 / 130.0).astype(float)
    zone = np.convolve(strong, np.ones(15), mode="same") > 0
    kerb = np.where(zone, np.where(curv > 0, 1, 2), 0).astype(int)

    # ── elevation cross-sections ──
    n = len(center)
    z5 = np.full((len(_XSEC), n), np.nan)
    dtm_key = conf.get("dtm") if conf else None
    dtm_obj = None
    if dtm_key and fit is not None and frame is not None:
        try:
            fitted_c = fit["s"] * ((center - fit["mu"]) @ fit["R"].T) + fit["t"]
            fitted_n = (nrm @ fit["R"].T)   # rotate normals into local frame
            ll_all = frame.to_latlon(fitted_c)
            dtm_obj = _DTM_PROVIDERS[dtm_key](meeting, ll_all[:, 0], ll_all[:, 1])
            for k, f in enumerate(_XSEC):
                pts = fitted_c + fitted_n * (f * hw[:, None] * 0.92)
                ll = frame.to_latlon(pts)
                z5[k] = dtm_obj.sample(ll[:, 0], ll[:, 1])
            sources["dtm"] = dtm_obj.name
        except Exception as exc:
            logger.warning("DTM sampling failed for %s: %s", meeting, exc)
            z5[:] = np.nan
            dtm_obj = None
    if not np.isfinite(z5).any():
        # fallback: telemetry z everywhere across the width (zero camber)
        base = race_z if np.isfinite(race_z).any() else np.zeros(n)
        for k in range(len(_XSEC)):
            z5[k] = base
        sources["dtm"] = "telemetry-z"

    # coarse/quantized grids (IGN 5 m): keep centre elevation, drop the
    # cross-slope — the "camber" would be interpolation noise
    if dtm_obj is not None and not dtm_obj.camber:
        for k in range(len(_XSEC)):
            z5[k] = z5[2].copy()

    # smooth along s (14 m window) and rebase to the lowest centre point
    for k in range(len(_XSEC)):
        z5[k] = _smooth(z5[k], 7)
    datum = float(np.nanmin(z5[2]))          # shared by surround/terrain
    z5 -= datum
    bank = np.degrees(np.arctan2(z5[-1] - z5[0], 2 * 0.92 * hw))

    # ── display frame: rotate like the 2D track map ──
    ang = rotation / 180.0 * np.pi
    cx, cy = _rotate(center[:, 0], center[:, 1], ang)
    tx, ty = _rotate(tang[:, 0], tang[:, 1], ang)
    nx, ny = -ty, tx

    # ── corners (rotated, with track distance) + curated names ──
    corner_names: dict[int, str] = {}
    straight_defs: list[tuple[int, str]] = []
    try:
        from config import HIST_CIRCUIT_KEY_MAP
        from tabs.track import _corner_name_map, _NAMED_STRAIGHTS
        ck = next((fr for fr, evs in HIST_CIRCUIT_KEY_MAP.items()
                   if _slug(meeting) in evs), None)
        if ck:
            corner_names = _corner_name_map(ck)
            straight_defs = _NAMED_STRAIGHTS.get(ck, [])
    except Exception as exc:
        logger.warning("corner names unavailable for %s: %s", meeting, exc)

    corners = []
    cdf = tm.get("corners")
    if cdf is not None and not cdf.empty and {"Number", "X", "Y"}.issubset(cdf.columns):
        ctree = cKDTree(np.column_stack([cx, cy]))
        cxr, cyr = _rotate(cdf["X"].to_numpy(float) * 0.1,
                           cdf["Y"].to_numpy(float) * 0.1, ang)
        _, cidx = ctree.query(np.column_stack([cxr, cyr]))
        for (_, row), ci in zip(cdf.iterrows(), cidx):
            num = int(row["Number"])
            corners.append({
                "n": num,
                "letter": str(row.get("Letter", "") or ""),
                "i": int(ci),
                "name": corner_names.get(num, ""),
            })

    # named straights: label the midpoint between `after_corner` and the next
    # corner (wrapping past the start/finish for the final one)
    straights = []
    idx_by_num = {c["n"]: c["i"] for c in corners}
    for after, sname in straight_defs:
        i0 = idx_by_num.get(int(after))
        nxt = idx_by_num.get(int(after) + 1)
        if i0 is None:
            continue
        if nxt is None:                          # last corner → wrap to first
            nxt = min(idx_by_num.values(), default=None)
            if nxt is None:
                continue
            mid = ((i0 + nxt + n) // 2) % n
        else:
            mid = (i0 + nxt) // 2 if nxt > i0 else ((i0 + nxt + n) // 2) % n
        straights.append({"i": int(mid), "name": sname})

    # ── surroundings: buildings / walls / trees / terrain (needs the geo
    #    transform; rendered in neutral greys by the viewer) ──
    surround = None
    if fit is not None and frame is not None and conf is not None:
        surround = _build_surround(meeting, conf, frame, fit, ang,
                                   np.asarray(cx), np.asarray(cy),
                                   z5[2], hw, datum, dtm_obj)

    # non-finite values would break JSON.parse in the browser
    r2 = lambda a: np.round(np.nan_to_num(np.asarray(a, float)), 2).tolist()
    bank = np.nan_to_num(bank)
    scene = {
        "v": _SCENE_VERSION, "season": int(season), "event": meeting,
        "slug": _slug(meeting), "n": int(n), "step": _STEP,
        "rotation": rotation,
        "dist": r2(dist), "cx": r2(cx), "cy": r2(cy),
        "nx": np.round(np.asarray(nx), 4).tolist(),
        "ny": np.round(np.asarray(ny), 4).tolist(),
        "hw": r2(hw),
        "xsec": _XSEC.tolist(),
        "z": [r2(z5[k]) for k in range(len(_XSEC))],
        "bank": np.round(bank, 1).tolist(),
        "kerb": kerb.tolist(),
        "corners": corners,
        "straights": straights,
        "elev_range": [0.0, float(np.round(np.nanmax(z5), 1))],
        "bank_max": float(np.round(np.nanmax(np.abs(bank)), 1)),
        "sources": sources,
        "geo": geo_meta,
        "surround": surround,
    }

    SCENES_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(scene_cache_path(season, meeting), "wt", encoding="utf-8") as fh:
        json.dump(scene, fh)
    return scene


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    season = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    meeting = sys.argv[2] if len(sys.argv) > 2 else "Dutch Grand Prix"
    sc = build_track_scene(season, meeting, force="--force" in sys.argv)
    if sc is None:
        print("no scene (no track map?)")
    else:
        print(f"{sc['event']} {sc['season']}: {sc['n']} sections, "
              f"track={sc['sources']['track']}, dtm={sc['sources']['dtm']}, "
              f"elev 0..{sc['elev_range'][1]} m, max bank {sc['bank_max']} deg, "
              f"georef median {sc['geo']['median_m']:.2f} m" if sc.get("geo")
              else "(no georef)")
