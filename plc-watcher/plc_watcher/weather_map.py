"""Render a weather map over the 1650 borders of the Polish–Lithuanian Commonwealth.

Open-Meteo (free, no key) supplies current conditions for a fixed set of
historically significant cities; matplotlib draws hand-built colored weather
icons over the Commonwealth border polygon vendored from
aourednik/historical-basemaps, styled like an old map plate.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import WEATHER_CITIES

log = logging.getLogger(__name__)

_GEOJSON_PATH = Path(__file__).parent / "data" / "plc_1650.geojson"

# WMO weather code → icon kind
def _wmo_kind(code: int | None) -> str:
    if code in (0, 1):
        return "sun"
    if code == 2:
        return "partly"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (82, 95, 96, 99):
        return "storm"
    return "rain"  # all drizzle/rain codes


# ── palette ──────────────────────────────────────────────────────────────────

SEA = "#1d3a4f"          # deep teal "old map sea"
LAND = "#e9d9ad"         # parchment
LAND_EDGE = "#a32638"    # crimson border
GLOW = "#f3e2c0"         # soft halo around the border
INK = "#2b1d12"          # dark ink for temps
LABEL = "#5a4634"        # muted brown for city names
CREAM = "#f3e9d2"        # title on dark sea

SUN_FC, SUN_EC = "#fdb813", "#e8920c"
CLOUD_FC, CLOUD_EC = "#dfe4ea", "#9aa6b2"
RAIN_C = "#4a90d9"
SNOW_C = "#bfe3f2"
BOLT_FC, BOLT_EC = "#ffd23f", "#e8920c"
FOG_C = "#aab4bd"


# ── icon drawing ─────────────────────────────────────────────────────────────


def _add_sun(da, cx, cy, r):
    import numpy as np
    from matplotlib.lines import Line2D
    from matplotlib.patches import Circle

    for ang in np.linspace(0, 2 * np.pi, 8, endpoint=False):
        x0 = cx + np.cos(ang) * (r + 1.5)
        x1 = cx + np.cos(ang) * (r + 4.5)
        y0 = cy + np.sin(ang) * (r + 1.5)
        y1 = cy + np.sin(ang) * (r + 4.5)
        da.add_artist(Line2D([x0, x1], [y0, y1], color=SUN_EC, linewidth=1.8,
                             solid_capstyle="round"))
    da.add_artist(Circle((cx, cy), r, fc=SUN_FC, ec=SUN_EC, linewidth=1.2))


def _add_cloud(da, cx, cy, scale=1.0):
    from matplotlib.patches import Circle, Ellipse

    base = Ellipse((cx, cy - 1.5 * scale), 19 * scale, 7.5 * scale,
                   fc=CLOUD_FC, ec=CLOUD_EC, linewidth=1.1)
    puffs = [
        Circle((cx - 5 * scale, cy), 4.2 * scale, fc=CLOUD_FC, ec=CLOUD_EC, linewidth=1.1),
        Circle((cx + 1 * scale, cy + 2.5 * scale), 5.2 * scale, fc=CLOUD_FC, ec=CLOUD_EC, linewidth=1.1),
        Circle((cx + 6 * scale, cy), 3.8 * scale, fc=CLOUD_FC, ec=CLOUD_EC, linewidth=1.1),
    ]
    for p in puffs:
        da.add_artist(p)
    da.add_artist(base)
    # repaint puffs borderless on top so internal edges vanish
    for p in puffs:
        c = Circle(p.center, p.radius - 0.05, fc=CLOUD_FC, ec="none")
        da.add_artist(c)
    da.add_artist(Ellipse(base.center, base.width - 0.1, base.height - 0.1,
                          fc=CLOUD_FC, ec="none"))


def _icon(kind: str):
    """Return a DrawingArea (28×26 pt) with the colored weather icon."""
    from matplotlib.lines import Line2D
    from matplotlib.offsetbox import DrawingArea
    from matplotlib.patches import Polygon as MplPolygon

    da = DrawingArea(28, 26, 0, 0)

    if kind == "sun":
        _add_sun(da, 14, 13, 6)
    elif kind == "partly":
        _add_sun(da, 9, 17, 4.5)
        _add_cloud(da, 16, 8, scale=0.95)
    elif kind == "cloud":
        _add_cloud(da, 14, 12)
    elif kind == "rain":
        _add_cloud(da, 14, 15, scale=0.9)
        for dx in (-5, 0, 5):
            da.add_artist(Line2D([14 + dx, 12.5 + dx], [8, 2.5], color=RAIN_C,
                                 linewidth=2.2, solid_capstyle="round"))
    elif kind == "snow":
        _add_cloud(da, 14, 15, scale=0.9)
        da.add_artist(Line2D([8.5, 14, 19.5], [4.5, 3, 4.5], linestyle="none",
                             marker="*", markersize=6.5, color=SNOW_C,
                             markeredgecolor="#8fc7dd", markeredgewidth=0.4))
    elif kind == "storm":
        _add_cloud(da, 14, 16, scale=0.9)
        da.add_artist(MplPolygon(
            [(14, 11), (18, 11), (14.5, 6.5), (17, 6.5), (10.5, 0),
             (13, 5.5), (10.8, 5.5)],
            closed=True, fc=BOLT_FC, ec=BOLT_EC, linewidth=0.8))
    elif kind == "fog":
        _add_cloud(da, 14, 17, scale=0.8)
        for y, (x0, x1) in zip((9, 6, 3), ((5, 23), (7, 21), (9, 19))):
            da.add_artist(Line2D([x0, x1], [y, y], color=FOG_C, linewidth=2.4,
                                 solid_capstyle="round", alpha=0.9))
    return da


# ── data ─────────────────────────────────────────────────────────────────────


def _fetch_current_weather() -> list[dict]:
    """One batched Open-Meteo call for all cities; returns [{name, lat, lon, temp, kind}]."""
    lats = ",".join(str(lat) for _, lat, _ in WEATHER_CITIES)
    lons = ",".join(str(lon) for _, _, lon in WEATHER_CITIES)
    resp = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lats,
            "longitude": lons,
            "current": "temperature_2m,weather_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    # Open-Meteo returns a list for multi-location requests, a dict for one.
    entries = payload if isinstance(payload, list) else [payload]

    out = []
    for (name, lat, lon), entry in zip(WEATHER_CITIES, entries):
        cur = entry.get("current", {})
        temp = cur.get("temperature_2m")
        if temp is None:
            continue
        out.append({
            "name": name,
            "lat": lat,
            "lon": lon,
            "temp": round(temp),
            "kind": _wmo_kind(cur.get("weather_code")),
        })
    return out


# ── render ───────────────────────────────────────────────────────────────────


def render_weather_map() -> bytes:
    """Return a PNG of current weather plotted over the Commonwealth's 1650 borders."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.patheffects as pe
    import matplotlib.pyplot as plt
    from matplotlib.offsetbox import AnnotationBbox

    geo = json.loads(_GEOJSON_PATH.read_text())
    geometry = geo["features"][0]["geometry"]
    polygons = (
        geometry["coordinates"]
        if geometry["type"] == "MultiPolygon"
        else [geometry["coordinates"]]
    )

    cities = _fetch_current_weather()

    fig, ax = plt.subplots(figsize=(10, 9), dpi=120)
    fig.patch.set_facecolor(SEA)
    ax.set_facecolor(SEA)

    for poly in polygons:
        for ring in poly:
            xs = [pt[0] for pt in ring]
            ys = [pt[1] for pt in ring]
            ax.fill(xs, ys, color=LAND, zorder=1)
            ax.plot(xs, ys, color=LAND_EDGE, linewidth=2.4, zorder=2,
                    path_effects=[pe.withStroke(linewidth=6, foreground=GLOW, alpha=0.35)])

    for c in cities:
        ax.plot(c["lon"], c["lat"], "o", color=INK, markersize=3.5, zorder=3)
        ax.add_artist(AnnotationBbox(
            _icon(c["kind"]), (c["lon"], c["lat"]),
            xybox=(-10, 16), boxcoords="offset points",
            frameon=False, zorder=5,
        ))
        ax.annotate(
            f"{c['temp']}°",
            (c["lon"], c["lat"]),
            xytext=(8, 12),
            textcoords="offset points",
            ha="left",
            fontsize=13,
            fontweight="bold",
            color=INK,
            zorder=4,
            path_effects=[pe.withStroke(linewidth=3, foreground=LAND)],
        )
        ax.annotate(
            c["name"],
            (c["lon"], c["lat"]),
            xytext=(0, -13),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            color=LABEL,
            style="italic",
            zorder=4,
            path_effects=[pe.withStroke(linewidth=2.5, foreground=LAND, alpha=0.8)],
        )

    ax.set_title(
        "Rzeczpospolita Obojga Narodów — pogoda dnia dzisiejszego",
        fontsize=16,
        color=CREAM,
        family="serif",
        style="italic",
        pad=14,
    )
    fig.text(
        0.985, 0.015,
        f"Merkuriusz Rzeczypospolitej · Anno Domini {datetime.now(timezone.utc):%Y}",
        ha="right", va="bottom", fontsize=8, color=CREAM, alpha=0.7, family="serif",
    )

    ax.set_aspect(1.6)  # rough lon/lat aspect correction at ~53°N
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    import io
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
