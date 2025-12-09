import json
from pathlib import Path
from datetime import datetime, timezone
from math import inf
import requests

# ========= SETTINGS =========

# NOTE:
# Replace coordinates / sensor_id with your own values locally.
# Do NOT push real personal coordinates or sensor IDs to public repos if privacy matters.

LOCATIONS = {
    "home": {
        "name": "My Home",
        "lat": 40.000000,
        "lon": 44.500000,
        "sensor_id": 83131,
    },
    "vanya": {
        "name": "Vanya's Home",
        "lat": 40.200000,
        "lon": 44.500000,
        "sensor_id": 80868,
    },
}

SENSOR_BASE_URL = "https://data.sensor.community/airrohr/v1/sensor/{sensor_id}/"
RADIUS_KM = 2          # radius (km) around the point for Sensor.Community
HOURS_HISTORY = 24     # how many hours of history to store + plot

RAINMETER_RESOURCES = (
    Path.home()
    / "Documents"
    / "Rainmeter"
    / "Skins"
    / "Hel_AQI"
    / "@Resources"
)
RAINMETER_RESOURCES.mkdir(parents=True, exist_ok=True)

VARS_FILE      = RAINMETER_RESOURCES / "aqi_data.inc"
STATE_FILE     = RAINMETER_RESOURCES / "aqi_last.json"
HISTORY_FILE   = RAINMETER_RESOURCES / "aqi_history.json"
GRAPH_FILE_HOME  = RAINMETER_RESOURCES / "aqi_graph_home.png"
GRAPH_FILE_VANYA = RAINMETER_RESOURCES / "aqi_graph_vanya.png"


# ========= SENSOR.COMMUNITY =========

def fetch_sensor_data(lat: float, lon: float, sensor_id: int | None = None, radius_km: int = 2):
    """
    Fetches data from Sensor.Community using filter/area.
    If sensor_id is provided — uses the latest entry for that sensor.
    Otherwise — picks the nearest sensor.
    Returns (pm25, pm10) in µg/m³ or (None, None).
    """
    url = f"https://data.sensor.community/airrohr/v1/filter/area={lat},{lon},{radius_km}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if not isinstance(data, list) or not data:
        print(f"[SC] No data for {lat},{lon}")
        return None, None

    def extract_pm(entry):
        pm25 = None
        pm10 = None
        for sv in entry.get("sensordatavalues", []):
            vt = sv.get("value_type")
            val = sv.get("value")
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue

            if vt in ("P2", "SDS_P2", "PM2.5", "pm2.5"):
                pm25 = val
            elif vt in ("P1", "SDS_P1", "PM10", "pm10"):
                pm10 = val
        return pm25, pm10

    candidate = None

    # 1) Try to take the correct sensor_id if provided
    if sensor_id is not None:
        latest_ts = None
        for entry in data:
            s = entry.get("sensor", {})
            if s.get("id") != sensor_id:
                continue
            ts = entry.get("timestamp") or entry.get("timestamp_measured")
            if ts and (latest_ts is None or ts > latest_ts):
                latest_ts = ts
                candidate = entry

    # 2) Otherwise: pick the nearest sensor
    if candidate is None:
        from math import radians, sin, cos, sqrt, atan2

        def dist_km(a_lat, a_lon, b_lat, b_lon):
            R = 6371.0
            dlat = radians(b_lat - a_lat)
            dlon = radians(b_lon - a_lon)
            A = (sin(dlat / 2) ** 2 +
                 cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlon / 2) ** 2)
            c = 2 * atan2(sqrt(A), sqrt(1 - A))
            return R * c

        best = None
        best_d = float("inf")
        for entry in data:
            loc = entry.get("location", {})
            slat = loc.get("latitude")
            slon = loc.get("longitude")
            try:
                slat = float(slat)
                slon = float(slon)
            except (TypeError, ValueError):
                continue

            d = dist_km(lat, lon, slat, slon)
            if d < best_d:
                best_d = d
                best = entry
        candidate = best

    if candidate is None:
        print(f"[SC] Failed to select sensor for {lat},{lon}")
        return None, None

    pm25, pm10 = extract_pm(candidate)
    print(f"[SC] {lat},{lon} -> PM2.5={pm25}, PM10={pm10}")
    return pm25, pm10


# ========= AQI CALCULATION =========

PM25_BREAKPOINTS = [
    (0.0, 12.0,   0,  50),
    (12.1, 35.4, 51, 100),
    (35.5, 55.4, 101,150),
    (55.5,150.4,151,200),
    (150.5,250.4,201,300),
    (250.5,500.4,301,500),
]

PM10_BREAKPOINTS = [
    (0,   54,  0,  50),
    (55, 154, 51, 100),
    (155,254,101,150),
    (255,354,151,200),
    (355,424,201,300),
    (425,604,301,500),
]

def calc_aqi_from_breakpoints(C: float, table) -> int | None:
    if C is None:
        return None
    for Clow, Chigh, Ilow, Ihigh in table:
        if Clow <= C <= Chigh:
            aqi = (Ihigh - Ilow) / (Chigh - Clow) * (C - Clow) + Ilow
            return round(aqi)
    return None

def calc_aqi(pm25: float | None, pm10: float | None) -> int | None:
    aqi25 = calc_aqi_from_breakpoints(pm25, PM25_BREAKPOINTS) if pm25 is not None else None
    aqi10 = calc_aqi_from_breakpoints(pm10, PM10_BREAKPOINTS) if pm10 is not None else None
    vals = [v for v in (aqi25, aqi10) if v is not None]
    if not vals:
        return None
    return max(vals)

def category_and_color(aqi: int) -> tuple[str, str]:
    if aqi <= 50:
        return "Good", "0,255,128,220"
    elif aqi <= 100:
        return "Moderate", "255,220,0,220"
    elif aqi <= 150:
        return "Unhealthy for sensitive", "255,153,0,220"
    elif aqi <= 200:
        return "Unhealthy", "255,51,51,220"
    elif aqi <= 300:
        return "Very unhealthy", "186,85,211,220"
    else:
        return "Hazardous", "128,0,64,220"

def trend_icon(new: int | None, old: int | None) -> str:
    if new is None or old is None:
        return "arrow_flat"
    if new > old:
        return "arrow_up"
    if new < old:
        return "arrow_down"
    return "arrow_flat"


# ========= STATE / HISTORY =========

def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default

def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def update_history(history: dict, key: str, ts: float, aqi: int | None,
                   pm25: float | None, pm10: float | None) -> None:
    """
    Stores history in format:
    {
      "home": [ {"ts": 1234567890.0, "aqi": 150, "pm25": 60, "pm10": 80}, ... ],
      "vanya": [...]
    }
    """
    entries = history.get(key, [])
    entries.append({
        "ts": ts,
        "aqi": aqi,
        "pm25": pm25,
        "pm10": pm10,
    })

    # Remove old entries
    max_age = HOURS_HISTORY * 3600
    entries = [e for e in entries if ts - e["ts"] <= max_age]

    history[key] = entries


# ========= GRAPHS =========

def save_daily_graph(history: dict) -> None:
    """
    Draws two PNG graphs of AQI for the past HOURS_HISTORY hours:
    - one for "home"
    - one for "vanya"
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[GRAPH] matplotlib not installed, skipping")
        return

    now_ts = datetime.now(timezone.utc).timestamp()
    left_ts = now_ts - HOURS_HISTORY * 3600

    def make_graph_for(key: str, out_path: Path, label: str, color: str):
        entries = history.get(key, [])
        if not entries:
            print(f"[GRAPH] No data for {key}")
            return

        xs = []
        ys = []
        for e in entries:
            ts = e.get("ts")
            aqi = e.get("aqi")
            if ts is None or aqi is None:
                continue
            if ts < left_ts:
                continue
            x = (ts - left_ts) / 3600.0
            xs.append(x)
            ys.append(aqi)

        if not xs or not ys:
            print(f"[GRAPH] Insufficient data for {key}")
            return

        fig, ax = plt.subplots(figsize=(4.5, 2.2), dpi=100)

        ax.plot(xs, ys, color=color, linewidth=1.8, label=label)

        ax.set_xlim(0, HOURS_HISTORY)

        # Axis labels (white)
        ax.set_xlabel("Hours (last 24h)", fontsize=8, color="white")
        ax.set_ylabel("AQI", fontsize=8, color="white")

        # Axis ticks (white)
        ax.tick_params(axis="x", colors="white")
        ax.tick_params(axis="y", colors="white")

        # Border (white)
        for spine in ax.spines.values():
            spine.set_color("white")

        # Grid
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.15, color="white")

        # Legend
        leg = ax.legend(fontsize=8, loc="upper left")
        for text in leg.get_texts():
            text.set_color("black")

        ax.set_facecolor("none")
        fig.patch.set_alpha(0.0)

        fig.tight_layout()
        fig.savefig(out_path, transparent=True)
        plt.close(fig)
        print(f"[GRAPH] saved {out_path}")

    make_graph_for(
        key="home",
        out_path=GRAPH_FILE_HOME,
        label="My Home",
        color="#00ff80"
    )

    make_graph_for(
        key="vanya",
        out_path=GRAPH_FILE_VANYA,
        label="Vanya's Home",
        color="#ff5599"
    )


# ========= MAIN =========

def main():
    prev_state = load_json(STATE_FILE, {})
    history = load_json(HISTORY_FILE, {})

    now = datetime.now(timezone.utc)
    now_iso = now.replace(microsecond=0).isoformat()
    now_ts = now.timestamp()

    lines = ["[Variables]"]
    new_state: dict = {}

    for key, cfg in LOCATIONS.items():
        lat = cfg["lat"]
        lon = cfg["lon"]
        name = cfg["name"]
        sensor_id = cfg.get("sensor_id")

        pm25, pm10 = fetch_sensor_data(lat, lon, sensor_id=sensor_id, radius_km=RADIUS_KM)
        aqi = calc_aqi(pm25, pm10)

        old_aqi = prev_state.get(key, {}).get("aqi")
        new_state[key] = {"aqi": aqi, "updated": now_iso}

        if aqi is None:
            color = "128,128,128,180"
            cat = "No data"
            aqi_str = "-"
            icon = "arrow_flat"
        else:
            cat, color = category_and_color(aqi)
            aqi_str = str(aqi)
            icon = trend_icon(aqi, old_aqi)

        update_history(history, key, now_ts, aqi, pm25, pm10)

        prefix = key.capitalize()
        lines.append(f"AQI_{prefix}={aqi_str}")
        lines.append(f"AQI_{prefix}Color={color}")
        lines.append(f"AQI_{prefix}TrendIcon={icon}")
        lines.append(f"AQI_{prefix}Category={cat}")
        lines.append(f"AQI_{prefix}Name={name}")
        lines.append(f"{prefix}_PM25={pm25 if pm25 is not None else '-'}")
        lines.append(f"{prefix}_PM10={pm10 if pm10 is not None else '-'}")

    lines.append(f"AQI_LastUpdateUTC={now_iso}")

    VARS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    save_json(STATE_FILE, new_state)
    save_json(HISTORY_FILE, history)

    print(">>> GENERATING GRAPH IMAGES <<<")

    save_daily_graph(history)


if __name__ == "__main__":
    main()
