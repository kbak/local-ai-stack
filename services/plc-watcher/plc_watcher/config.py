import json
import os

# RSS feeds grouped by modern country overlapping the Commonwealth:
# {"Korona (Polska)": ["url1", ...], "Litwa": [...]}
PLC_FEEDS: dict[str, list[str]] = json.loads(os.environ.get("PLC_FEEDS", "{}"))

# How many hours back to include per run (matches the daily cadence)
PLC_LOOKBACK_HOURS: int = int(os.environ.get("PLC_LOOKBACK_HOURS", "24"))

# Phone number or group.<id> — falls back to BRIEFING_RECIPIENT for testing
PLC_RECIPIENT: str = os.environ.get("PLC_RECIPIENT") or os.environ["BRIEFING_RECIPIENT"]

# Chatterbox voice-sample stem for the Polish voice note (None = default voice)
PLC_VOICE: str | None = os.environ.get("PLC_VOICE") or None

# Cities sampled for the weather map: (display name, lat, lon)
WEATHER_CITIES: list[tuple[str, float, float]] = [
    ("Warszawa", 52.23, 21.01),
    ("Kraków", 50.06, 19.94),
    ("Gdańsk", 54.35, 18.65),
    ("Poznań", 52.41, 16.93),
    ("Lublin", 51.25, 22.57),
    ("Wilno", 54.69, 25.28),
    ("Kowno", 54.90, 23.91),
    ("Ryga", 56.95, 24.11),
    ("Dyneburg", 55.87, 26.54),
    ("Mińsk", 53.90, 27.57),
    ("Połock", 55.49, 28.79),
    ("Brześć", 52.10, 23.69),
    ("Kijów", 50.45, 30.52),
    ("Lwów", 49.84, 24.03),
    ("Kamieniec Podolski", 48.68, 26.58),
    ("Smoleńsk", 54.78, 32.05),
]
