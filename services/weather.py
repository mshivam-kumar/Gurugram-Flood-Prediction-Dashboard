"""Live rainfall retrieval for the Gurugram dashboard."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List
from urllib.parse import urlencode
from urllib.request import urlopen

from app.config import get_config


logger = logging.getLogger(__name__)


@dataclass
class RainfallForecast:
    hourly_mm: List[float]
    source: str
    generated_at: str
    current_rainfall_mm_hr: float = 0.0

    @property
    def total_mm(self) -> float:
        return float(sum(self.hourly_mm))

    @property
    def peak_intensity_mm_hr(self) -> float:
        return float(max(self.hourly_mm or [0.0]))

    @property
    def peak_hour(self) -> int:
        if not self.hourly_mm:
            return 0
        return int(self.hourly_mm.index(max(self.hourly_mm)))

    def to_dict(self) -> dict:
        return {
            "hourly_mm": [round(value, 3) for value in self.hourly_mm],
            "current_rainfall_mm_hr": round(self.current_rainfall_mm_hr, 3),
            "total_mm": round(self.total_mm, 3),
            "peak_intensity_mm_hr": round(self.peak_intensity_mm_hr, 3),
            "peak_hour": self.peak_hour,
            "duration_hours": len(self.hourly_mm),
            "source": self.source,
            "generated_at": self.generated_at,
        }


def _get_json(url: str, params: dict) -> dict:
    query = urlencode(params)
    with urlopen(f"{url}?{query}", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _demo_forecast(hours: int) -> RainfallForecast:
    values: List[float] = []
    for hour in range(hours):
        if hour < 2:
            rain = 1.5 * hour
        elif hour < 5:
            rain = 4.0 + (hour - 2) * 8.0
        elif hour < 8:
            rain = 28.0 - (hour - 5) * 4.5
        elif hour < 12:
            rain = 12.0 - (hour - 8) * 2.5
        else:
            rain = max(0.0, 2.0 - (hour - 12) * 0.25)
        values.append(max(0.0, rain))
    return RainfallForecast(
        hourly_mm=values,
        current_rainfall_mm_hr=values[0] if values else 0.0,
        source="demo_no_api_key",
        generated_at=datetime.now().isoformat(),
    )


def fetch_live_rainfall(hours: int = 12) -> RainfallForecast:
    """Fetch live rainfall forecast when an OpenWeatherMap key is configured."""
    config = get_config()
    if not config.openweather_api_key:
        return _demo_forecast(hours)

    base_params = {
        "lat": config.weather_latitude,
        "lon": config.weather_longitude,
        "appid": config.openweather_api_key,
        "units": "metric",
    }
    try:
        current_data = _get_json("https://api.openweathermap.org/data/2.5/weather", base_params)
        forecast_data = _get_json("https://api.openweathermap.org/data/2.5/forecast", base_params)
    except Exception as exc:
        logger.warning("Live rainfall fetch failed, using demo forecast: %s", exc)
        fallback = _demo_forecast(hours)
        fallback.source = "demo_weather_fetch_failed"
        return fallback

    current_rain = float(current_data.get("rain", {}).get("1h", 0.0))
    hourly: List[float] = []
    for item in forecast_data.get("list", []):
        rain_3h = float(item.get("rain", {}).get("3h", 0.0))
        hourly.extend([rain_3h / 3.0] * 3)
        if len(hourly) >= hours:
            break
    while len(hourly) < hours:
        hourly.append(0.0)

    return RainfallForecast(
        hourly_mm=hourly[:hours],
        current_rainfall_mm_hr=current_rain,
        source="openweathermap",
        generated_at=datetime.now().isoformat(),
    )
