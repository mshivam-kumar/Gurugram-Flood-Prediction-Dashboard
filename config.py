"""Application configuration for the dashboard prototype."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
RAINFALL_DIR = DATA_DIR / "rainfall_csv"
CHECKPOINTS_DIR = PROJECT_ROOT / "checkpoints"
STATIC_DIR = APP_DIR / "static"
ASSETS_DIR = APP_DIR / "assets"
STATIC_SCENARIO_DIR = ASSETS_DIR / "static_scenarios"
DYNAMIC_RUN_DIR = ASSETS_DIR / "dynamic_runs"


@dataclass(frozen=True)
class GeoBounds:
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    @property
    def leaflet_bounds(self) -> List[List[float]]:
        return [
            [self.min_lat, self.min_lon],
            [self.max_lat, self.max_lon],
        ]


@dataclass(frozen=True)
class CityProfile:
    city_name: str
    state: str
    country: str
    bounds: GeoBounds
    grid_shape: List[int]
    cell_size_m: float
    timestep_minutes: int


@dataclass(frozen=True)
class AppConfig:
    title: str = "Gurugram Flood Prediction"
    subtitle: str = "Urban Flood Prediction Dashboard"
    host: str = "0.0.0.0"
    port: int = 8009
    debug: bool = False
    default_static_scenario: str = "random_350"
    default_layer: str = "water_depth"
    static_layer_names: tuple[str, ...] = (
        "water_depth",
        "hazard_band",
        "flood_extent",
        "risk_cells",
    )
    static_context_layers: tuple[str, ...] = ("city_bounds",)
    openweather_api_key: str = ""
    weather_latitude: float = 28.4595
    weather_longitude: float = 77.0266


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig(openweather_api_key=os.getenv("OPENWEATHERMAP_API_KEY", ""))


@lru_cache(maxsize=1)
def get_city_profile() -> CityProfile:
    raw = json.loads((APP_DIR / "data" / "city_profiles" / "gurugram.json").read_text())
    bounds = GeoBounds(**raw["bounds"])
    return CityProfile(
        city_name=raw["city_name"],
        state=raw["state"],
        country=raw["country"],
        bounds=bounds,
        grid_shape=raw["grid_shape"],
        cell_size_m=raw["cell_size_m"],
        timestep_minutes=raw.get("timestep_minutes", 15),
    )


def ensure_app_dirs() -> None:
    for path in (ASSETS_DIR, STATIC_SCENARIO_DIR, DYNAMIC_RUN_DIR, STATIC_DIR):
        path.mkdir(parents=True, exist_ok=True)
