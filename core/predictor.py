"""Prediction engine for dynamic dashboard mode."""

from __future__ import annotations

import importlib.util
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import torch


logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = APP_DIR.parent
MODELS_DIR = PROJECT_ROOT / "models"
CHECKPOINT_DIR = PROJECT_ROOT / "checkpoints"
DATA_DIR = PROJECT_ROOT / "data" / "processed"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class TimeStep:
    timestamp: datetime
    minutes_from_start: int
    label: str
    rainfall_mm_hr: float
    water_depth: np.ndarray
    max_depth_m: float
    flooded_area_km2: float
    flooded_cells: int
    risk_low: int
    risk_moderate: int
    risk_high: int
    risk_severe: int

    def summary(self, idx: int) -> Dict[str, object]:
        return {
            "idx": idx,
            "timestamp": self.timestamp.isoformat(),
            "minutes_from_start": self.minutes_from_start,
            "label": self.label,
            "rainfall_mm_hr": round(self.rainfall_mm_hr, 3),
            "max_depth_m": round(self.max_depth_m, 3),
            "flooded_area_km2": round(self.flooded_area_km2, 3),
            "flooded_cells": self.flooded_cells,
            "risk": {
                "low": self.risk_low,
                "moderate": self.risk_moderate,
                "high": self.risk_high,
                "severe": self.risk_severe,
            },
        }


@dataclass
class Forecast:
    frames: List[TimeStep]
    generated_at: datetime
    total_inference_ms: float

    def summary(self) -> Dict[str, object]:
        peak = max(self.frames, key=lambda item: item.max_depth_m) if self.frames else None
        return {
            "generated_at": self.generated_at.isoformat(),
            "num_frames": len(self.frames),
            "total_inference_ms": round(self.total_inference_ms, 1),
            "peak_depth_m": round(peak.max_depth_m, 3) if peak else 0.0,
            "peak_label": peak.label if peak else "N/A",
            "peak_timestamp": peak.timestamp.isoformat() if peak else self.generated_at.isoformat(),
            "frames": [frame.summary(idx) for idx, frame in enumerate(self.frames)],
        }


def _label(minutes: int) -> str:
    if minutes == 0:
        return "0h"
    hours = minutes / 60
    if abs(hours - round(hours)) < 1e-8:
        return f"{int(round(hours))}h"
    return f"{hours:.2f}h"


class FloodPredictor:
    def __init__(self, device: str = "auto"):
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)
        self._loaded = False
        self._model = None
        self._dem = None
        self._x_coord = None
        self._y_coord = None
        self._drainage_potential = None
        self._distance_to_drain = None
        self.grid_shape = None
        self.resolution_m = 28.48
        self.rainfall_log_reference = float(np.log1p(60.0))

    def load(self) -> None:
        self._load_static_features()
        self._load_model()
        self._loaded = True

    def _load_static_features(self) -> None:
        dem_path = DATA_DIR / "dem_normalized.npy"
        x_path = DATA_DIR / "x_coord.npy"
        y_path = DATA_DIR / "y_coord.npy"
        drain_potential_path = DATA_DIR / "drainage_drainage_potential.npy"
        drain_distance_path = DATA_DIR / "drainage_distance_to_drain.npy"

        self._dem = np.load(dem_path).astype(np.float32)
        self._x_coord = np.load(x_path).astype(np.float32)
        self._y_coord = np.load(y_path).astype(np.float32)
        self._drainage_potential = np.load(drain_potential_path).astype(np.float32)
        distance = np.load(drain_distance_path).astype(np.float32)
        self._distance_to_drain = distance / (distance.max() + 1e-8)
        self.grid_shape = self._dem.shape

    def _load_model(self) -> None:
        model_path = CHECKPOINT_DIR / "pgarfno_v2" / "best_model.pt"
        if not model_path.exists():
            fallback = CHECKPOINT_DIR / "best.pt"
            if fallback.exists():
                model_path = fallback
            else:
                raise FileNotFoundError(f"Model checkpoint not found at {model_path}")

        arch_path = MODELS_DIR / "pg_ar_fno.py"
        spec = importlib.util.spec_from_file_location("pg_ar_fno", arch_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load model architecture from {arch_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        checkpoint = torch.load(model_path, map_location=self.device, weights_only=False)
        state = checkpoint.get("model_state_dict", checkpoint)
        model = module.PGARFNO(
            in_channels=8,
            width=32,
            modes_x=16,
            modes_y=16,
            n_layers=4,
        )
        model.load_state_dict(state, strict=False)
        self._model = model.to(self.device).eval()

    def _prepare_input(self, rainfall_mm_hr: float, cumulative_mm: float, prev_depth: Optional[np.ndarray]) -> tuple[torch.Tensor, torch.Tensor]:
        h, w = self.grid_shape
        rain = np.full((h, w), np.log1p(rainfall_mm_hr) / self.rainfall_log_reference, dtype=np.float32)
        rain_cum = np.full((h, w), np.log1p(cumulative_mm) / self.rainfall_log_reference, dtype=np.float32)
        features = np.stack(
            [
                self._x_coord,
                self._y_coord,
                self._dem,
                rain,
                rain_cum,
                self._drainage_potential,
                self._distance_to_drain,
            ],
            axis=-1,
        )
        x = torch.from_numpy(features[None, ...]).to(self.device)
        if prev_depth is None:
            h_prev = torch.zeros((1, h, w, 1), device=self.device)
        else:
            h_prev = torch.from_numpy(prev_depth[None, ..., None]).to(self.device)
        return x, h_prev

    def _rain_scale(self, rainfall_mm_hr: float) -> float:
        if rainfall_mm_hr < 0.5:
            return 0.0
        if rainfall_mm_hr < 2.5:
            return 0.005 + (rainfall_mm_hr - 0.5) * 0.0125
        if rainfall_mm_hr < 7.5:
            normalized = (rainfall_mm_hr - 2.5) / 5.0
            return 0.03 + (normalized ** 1.5) * 0.77
        return 1.0

    @torch.no_grad()
    def predict(self, rainfall_hourly: List[float], hours: Optional[int] = None, timestep_minutes: int = 15) -> Forecast:
        if not self._loaded:
            self.load()

        if hours is None:
            hours = len(rainfall_hourly)
        total_steps = int(hours * 60 // timestep_minutes)
        steps_per_hour = max(1, 60 // timestep_minutes)
        rainfall_steps: List[float] = []
        for hour_idx in range(hours):
            rain_val = rainfall_hourly[hour_idx] if hour_idx < len(rainfall_hourly) else 0.0
            rainfall_steps.extend([rain_val] * steps_per_hour)
        rainfall_steps = rainfall_steps[:total_steps]

        start = time.perf_counter()
        now = datetime.now()
        prev_depth = None
        cumulative = 0.0
        frames: List[TimeStep] = []
        cell_area_km2 = (self.resolution_m * self.resolution_m) / 1e6

        for step_idx, rain_mm_hr in enumerate(rainfall_steps):
            cumulative += rain_mm_hr * (timestep_minutes / 60.0)
            x, h_prev = self._prepare_input(rain_mm_hr, cumulative, prev_depth)
            raw = self._model(x, h_prev)[0, :, :, 0].cpu().numpy().astype(np.float32)
            prev_depth = raw
            depth = np.maximum(raw, 0.0) * self._rain_scale(rain_mm_hr)
            flooded_cells = int((depth >= 0.1).sum())
            minutes = step_idx * timestep_minutes
            frames.append(
                TimeStep(
                    timestamp=now + timedelta(minutes=minutes),
                    minutes_from_start=minutes,
                    label=_label(minutes),
                    rainfall_mm_hr=rain_mm_hr,
                    water_depth=depth,
                    max_depth_m=float(depth.max()),
                    flooded_area_km2=flooded_cells * cell_area_km2,
                    flooded_cells=flooded_cells,
                    risk_low=int(((depth >= 0.1) & (depth < 0.3)).sum()),
                    risk_moderate=int(((depth >= 0.3) & (depth < 0.5)).sum()),
                    risk_high=int(((depth >= 0.5) & (depth < 1.0)).sum()),
                    risk_severe=int((depth >= 1.0).sum()),
                )
            )

        return Forecast(frames=frames, generated_at=now, total_inference_ms=(time.perf_counter() - start) * 1000)

    def get_model_info(self) -> Dict[str, object]:
        return {
            "loaded": self._loaded,
            "device": str(self.device),
            "grid_shape": list(self.grid_shape) if self.grid_shape else [],
            "model": "PG-AR-FNO",
        }


_predictor: Optional[FloodPredictor] = None


def get_predictor() -> FloodPredictor:
    global _predictor
    if _predictor is None:
        _predictor = FloodPredictor()
        _predictor.load()
    return _predictor
