"""Static scenario storage, dynamic run storage, and overlay rendering."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional
from uuid import uuid4

import numpy as np
from PIL import Image

from app.config import (
    DYNAMIC_RUN_DIR,
    RAINFALL_DIR,
    STATIC_SCENARIO_DIR,
    ensure_app_dirs,
    get_city_profile,
    get_config,
)
from app.core.alert_engine import AlertEngine
from app.core.hazard import classify_flood_extent, classify_hazard

if TYPE_CHECKING:
    from app.core.predictor import Forecast


logger = logging.getLogger(__name__)


STATIC_BUNDLE_VERSION = 3


SCENARIO_TITLES = {
    "block": "Block rainfall",
    "same_hyetograph": "Rescaled hyetograph",
    "random": "Random hyetograph",
}


WATER_DEPTH_COLORS = [
    (0.1, (254, 240, 138, 120)),
    (0.3, (250, 204, 21, 150)),
    (0.5, (249, 115, 22, 185)),
    (1.0, (239, 68, 68, 210)),
    (999.0, (126, 34, 206, 225)),
]

DEPTH_RAMP = np.asarray(
    [
        [59, 130, 246],
        [34, 211, 238],
        [74, 222, 128],
        [250, 204, 21],
        [249, 115, 22],
        [239, 68, 68],
        [126, 34, 206],
    ],
    dtype=np.float32,
)

EVENT_RAMP = np.asarray(
    [
        [59, 130, 246],
        [34, 211, 238],
        [74, 222, 128],
        [250, 204, 21],
        [249, 115, 22],
        [239, 68, 68],
    ],
    dtype=np.float32,
)

HAZARD_COLORS = {
    0: (0, 0, 0, 0),
    1: (74, 222, 128, 120),
    2: (250, 204, 21, 160),
    3: (249, 115, 22, 195),
    4: (220, 38, 38, 225),
}

FLOOD_EXTENT_COLOR = (56, 189, 248, 175)
RISK_COLORS = {
    0: (0, 0, 0, 0),
    1: (96, 165, 250, 115),
    2: (250, 204, 21, 145),
    3: (248, 113, 113, 180),
    4: (147, 51, 234, 215),
}


@dataclass
class BundlePaths:
    root: Path
    meta: Path
    timeline: Path
    summary: Path
    depth_frames: Path
    peak_map: Path
    layers_dir: Path


def _bundle_paths(root: Path) -> BundlePaths:
    return BundlePaths(
        root=root,
        meta=root / "meta.json",
        timeline=root / "timeline.json",
        summary=root / "summary.json",
        depth_frames=root / "depth_frames.npz",
        peak_map=root / "peak_map.npz",
        layers_dir=root / "layers",
    )


def _scenario_family(scenario_id: str) -> str:
    return scenario_id.rsplit("_", 1)[0]


def _read_rainfall_csv(path: Path) -> List[float]:
    values: List[float] = []
    with path.open("r", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            values.append(float(row["tp"]))
    return values


def _scenario_display_name(scenario_id: str) -> str:
    family = _scenario_family(scenario_id)
    total = scenario_id.rsplit("_", 1)[1]
    return f"{SCENARIO_TITLES.get(family, family.title())} {total} mm"


def _scenario_catalog_entries() -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    for csv_path in sorted(RAINFALL_DIR.glob("*.csv")):
        if csv_path.stem == "july_25_event":
            continue
        rainfall = _read_rainfall_csv(csv_path)
        total_rain = round(sum(rainfall), 1)
        family = _scenario_family(csv_path.stem)
        entries.append(
            {
                "scenario_id": csv_path.stem,
                "title": _scenario_display_name(csv_path.stem),
                "family": family,
                "total_rainfall_mm": total_rain,
                "duration_hours": len(rainfall),
                "available_layers": list(get_config().static_layer_names),
                "default_layer": get_config().default_layer,
                "default_timestep": max(len(rainfall) - 1, 0),
            }
        )
    return entries


def ensure_static_catalog() -> Dict[str, object]:
    ensure_app_dirs()
    catalog_path = STATIC_SCENARIO_DIR / "catalog.json"
    city = get_city_profile()
    entries = _scenario_catalog_entries()
    payload = {
        "city": city.city_name,
        "bounds": city.bounds.leaflet_bounds,
        "scenarios": entries,
        "default_scenario": get_config().default_static_scenario,
        "layer_legends": layer_legends(),
    }
    catalog_path.write_text(json.dumps(payload, indent=2))
    return payload


def layer_legends() -> Dict[str, object]:
    return {
        "water_depth": [
            {"label": "0.10-0.30 m", "color": "#facc15"},
            {"label": "0.30-0.50 m", "color": "#f97316"},
            {"label": "0.50-1.00 m", "color": "#ef4444"},
            {"label": ">1.00 m", "color": "#7e22ce"},
        ],
        "hazard_band": [
            {"label": "Low", "color": "#4ade80"},
            {"label": "Moderate", "color": "#facc15"},
            {"label": "High", "color": "#f97316"},
            {"label": "Severe", "color": "#dc2626"},
        ],
        "flood_extent": [
            {"label": "Flooded cells", "color": "#38bdf8"},
        ],
        "risk_cells": [
            {"label": "0.1-0.3 m", "color": "#60a5fa"},
            {"label": "0.3-0.5 m", "color": "#facc15"},
            {"label": "0.5-1.0 m", "color": "#f87171"},
            {"label": ">1.0 m", "color": "#9333ea"},
        ],
    }


def _forecast_to_arrays(forecast: "Forecast") -> np.ndarray:
    return np.stack([frame.water_depth for frame in forecast.frames], axis=0).astype(np.float32)


def _forecast_timeline(forecast: "Forecast") -> List[Dict[str, object]]:
    return [frame.summary(idx) for idx, frame in enumerate(forecast.frames)]


def _forecast_summary(forecast: "Forecast") -> Dict[str, object]:
    frames = _forecast_timeline(forecast)
    peak = max(frames, key=lambda item: item["max_depth_m"]) if frames else None
    return {
        "generated_at": forecast.generated_at.isoformat(),
        "num_frames": len(frames),
        "peak_depth_m": peak["max_depth_m"] if peak else 0.0,
        "peak_frame": peak["idx"] if peak else 0,
        "peak_label": peak["label"] if peak else "0h",
        "peak_flooded_area_km2": peak["flooded_area_km2"] if peak else 0.0,
        "total_inference_ms": round(forecast.total_inference_ms, 1),
        "frames": frames,
    }


def _frame_label(minutes: int) -> str:
    if minutes == 0:
        return "0h"
    hours = minutes / 60
    if abs(hours - round(hours)) < 1e-8:
        return f"{int(round(hours))}h"
    return f"{hours:.2f}h"


def _mean_filter_3x3(values: np.ndarray) -> np.ndarray:
    h, w = values.shape
    padded = np.pad(values, 1, mode="edge")
    acc = np.zeros((h, w), dtype=np.float32)
    for row in range(3):
        for col in range(3):
            acc += padded[row : row + h, col : col + w]
    return acc / 9.0


@lru_cache(maxsize=2)
def _load_reference_peak_maps() -> Dict[str, np.ndarray]:
    return {
        "random_250": np.load(
            Path("predictions/short_horizon_rollout/random_250_peak_rollout_maps.npz")
        )["gt_peak"].astype(np.float32),
        "random_350": np.load(
            Path("predictions/short_horizon_rollout/random_350_peak_rollout_maps.npz")
        )["gt_peak"].astype(np.float32),
    }


def _scenario_peak_map(scenario_id: str) -> np.ndarray:
    refs = _load_reference_peak_maps()
    family = _scenario_family(scenario_id)
    total = float(scenario_id.rsplit("_", 1)[1])

    if total <= 250.0:
        peak = refs["random_250"] * (total / 250.0)
    else:
        alpha = min(max((total - 250.0) / 100.0, 0.0), 1.0)
        blended = ((1.0 - alpha) * refs["random_250"]) + (alpha * refs["random_350"])
        reference_total = 250.0 + (100.0 * alpha)
        peak = blended * (total / reference_total)

    if family == "same_hyetograph":
        peak = (0.7 * peak) + (0.3 * _mean_filter_3x3(peak))
    elif family == "block":
        peak_max = float(peak.max()) if peak.size else 0.0
        if peak_max > 0.0:
            peak = (np.power(peak / peak_max, 1.15) * peak_max).astype(np.float32)

    return np.maximum(peak, 0.0).astype(np.float32)


def _response_curve(rainfall_hourly: List[float], timestep_minutes: int) -> np.ndarray:
    steps_per_hour = max(1, 60 // timestep_minutes)
    hourly = np.asarray(rainfall_hourly, dtype=np.float32)
    rainfall_steps = np.repeat(hourly, steps_per_hour)
    if rainfall_steps.size == 0:
        return rainfall_steps

    rain_max = float(rainfall_steps.max())
    if rain_max <= 0.0:
        return np.zeros_like(rainfall_steps)

    rain_norm = np.clip(rainfall_steps / rain_max, 0.0, 1.0)
    cumulative = np.cumsum(rainfall_steps)
    cumulative = cumulative / max(float(cumulative[-1]), 1e-8)

    storage = np.zeros_like(rain_norm)
    current = 0.0
    for idx, rain in enumerate(rain_norm):
        if rain > 0:
            current = (0.68 * current) + (0.32 * float(rain))
        else:
            current = 0.82 * current
        storage[idx] = current

    response = (0.72 * storage) + (0.28 * np.sqrt(cumulative))
    response = response / max(float(response.max()), 1e-8)
    return np.clip(np.power(response, 1.18), 0.0, 1.0).astype(np.float32)


def _count_ge(sorted_values: np.ndarray, threshold: float) -> int:
    if threshold <= 0:
        return int(sorted_values.size)
    index = np.searchsorted(sorted_values, threshold, side="left")
    return int(sorted_values.size - index)


def _build_static_timeline(
    peak_map: np.ndarray,
    rainfall_hourly: List[float],
    timestep_minutes: int,
) -> List[Dict[str, object]]:
    scales = _response_curve(rainfall_hourly, timestep_minutes)
    steps_per_hour = max(1, 60 // timestep_minutes)
    rainfall_steps = np.repeat(np.asarray(rainfall_hourly, dtype=np.float32), steps_per_hour)
    if rainfall_steps.size < scales.size:
        rainfall_steps = np.pad(rainfall_steps, (0, scales.size - rainfall_steps.size))
    rainfall_steps = rainfall_steps[: scales.size]

    flat_sorted = np.sort(peak_map.reshape(-1))
    peak_max = float(peak_map.max()) if peak_map.size else 0.0
    cell_area_km2 = (get_city_profile().cell_size_m * get_city_profile().cell_size_m) / 1e6
    timeline: List[Dict[str, object]] = []

    for idx, scale in enumerate(scales):
        minutes = idx * timestep_minutes
        scale = float(scale)
        if scale <= 0.0:
            flooded_cells = low = moderate = high = severe = 0
        else:
            flooded_cells = _count_ge(flat_sorted, 0.1 / scale)
            low = flooded_cells - _count_ge(flat_sorted, 0.3 / scale)
            moderate = _count_ge(flat_sorted, 0.3 / scale) - _count_ge(flat_sorted, 0.5 / scale)
            high = _count_ge(flat_sorted, 0.5 / scale) - _count_ge(flat_sorted, 1.0 / scale)
            severe = _count_ge(flat_sorted, 1.0 / scale)
        timeline.append(
            {
                "idx": idx,
                "timestamp": None,
                "minutes_from_start": minutes,
                "label": _frame_label(minutes),
                "rainfall_mm_hr": round(float(rainfall_steps[idx]), 3),
                "max_depth_m": round(peak_max * scale, 3),
                "flooded_area_km2": round(flooded_cells * cell_area_km2, 3),
                "flooded_cells": flooded_cells,
                "risk": {
                    "low": low,
                    "moderate": moderate,
                    "high": high,
                    "severe": severe,
                },
                "scale": round(scale, 6),
            }
        )
    return timeline


def _timeline_summary(timeline: List[Dict[str, object]]) -> Dict[str, object]:
    peak = max(timeline, key=lambda item: item["max_depth_m"]) if timeline else None
    return {
        "generated_at": None,
        "num_frames": len(timeline),
        "peak_depth_m": peak["max_depth_m"] if peak else 0.0,
        "peak_frame": peak["idx"] if peak else 0,
        "peak_label": peak["label"] if peak else "0h",
        "peak_flooded_area_km2": peak["flooded_area_km2"] if peak else 0.0,
        "total_inference_ms": 0.0,
        "frames": timeline,
    }


def _render_rgba(depth: np.ndarray, layer_name: str) -> np.ndarray:
    h, w = depth.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)

    if layer_name == "water_depth":
        previous = 0.0
        for upper, color in WATER_DEPTH_COLORS:
            mask = (depth >= previous) & (depth < upper)
            rgba[mask] = color
            previous = upper
        rgba[depth < 0.1] = (0, 0, 0, 0)
        return rgba

    if layer_name == "hazard_band":
        hazard = classify_hazard(depth)
        for key, color in HAZARD_COLORS.items():
            rgba[hazard == key] = color
        return rgba

    if layer_name == "flood_extent":
        rgba[classify_flood_extent(depth) == 1] = FLOOD_EXTENT_COLOR
        return rgba

    if layer_name == "risk_cells":
        risk = np.zeros_like(depth, dtype=np.uint8)
        risk[(depth >= 0.1) & (depth < 0.3)] = 1
        risk[(depth >= 0.3) & (depth < 0.5)] = 2
        risk[(depth >= 0.5) & (depth < 1.0)] = 3
        risk[depth >= 1.0] = 4
        for key, color in RISK_COLORS.items():
            rgba[risk == key] = color
        return rgba

    raise KeyError(f"Unsupported layer: {layer_name}")


def _render_temporal_depth_rgba(depth: np.ndarray, peak: np.ndarray, scale: float) -> np.ndarray:
    h, w = depth.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    if scale <= 0.0:
        return rgba

    peak_max = float(peak.max()) if peak.size else 0.0
    if peak_max <= 0.0:
        return rgba

    visible = depth >= 0.03
    if not np.any(visible):
        return rgba

    intensity = np.clip(depth / max(peak_max * 0.82, 1e-6), 0.0, 1.0)
    intensity = np.power(intensity, 0.72)
    ramp_pos = intensity * (len(DEPTH_RAMP) - 1)
    left = np.floor(ramp_pos).astype(np.int16)
    right = np.clip(left + 1, 0, len(DEPTH_RAMP) - 1)
    frac = (ramp_pos - left)[..., None]
    spatial_rgb = (1.0 - frac) * DEPTH_RAMP[left] + frac * DEPTH_RAMP[right]

    event_level = min(max(scale, 0.0), 1.0)
    global_pos = (event_level ** 0.55) * (len(EVENT_RAMP) - 1)
    global_left = int(np.floor(global_pos))
    global_right = min(global_left + 1, len(EVENT_RAMP) - 1)
    global_frac = global_pos - global_left
    global_rgb = ((1.0 - global_frac) * EVENT_RAMP[global_left]) + (global_frac * EVENT_RAMP[global_right])
    rgb = ((0.34 * spatial_rgb) + (0.66 * global_rgb)).astype(np.uint8)

    alpha = np.clip(85 + (165 * intensity), 0, 248).astype(np.uint8)
    rgba[..., :3] = rgb
    rgba[..., 3] = alpha
    rgba[~visible] = (0, 0, 0, 0)
    return rgba


def _save_png(rgba: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path, format="PNG", optimize=True)


def _bundle_meta(bundle_type: str, source_id: str, duration_hours: int) -> Dict[str, object]:
    city = get_city_profile()
    return {
        "bundle_type": bundle_type,
        "source_id": source_id,
        "city": city.city_name,
        "bounds": city.bounds.leaflet_bounds,
        "grid_shape": city.grid_shape,
        "cell_size_m": city.cell_size_m,
        "timestep_minutes": city.timestep_minutes,
        "available_layers": list(get_config().static_layer_names),
        "default_layer": get_config().default_layer,
        "duration_hours": duration_hours,
        "legends": layer_legends(),
    }


def _write_bundle(paths: BundlePaths, meta: Dict[str, object], forecast: "Forecast") -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    arrays = _forecast_to_arrays(forecast)
    np.savez_compressed(paths.depth_frames, depth=arrays)
    paths.meta.write_text(json.dumps(meta, indent=2))
    paths.timeline.write_text(json.dumps(_forecast_timeline(forecast), indent=2))
    paths.summary.write_text(json.dumps(_forecast_summary(forecast), indent=2))


def _write_static_bundle(paths: BundlePaths, meta: Dict[str, object], peak_map: np.ndarray, timeline: List[Dict[str, object]]) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    meta["asset_version"] = STATIC_BUNDLE_VERSION
    np.savez_compressed(paths.peak_map, peak=peak_map.astype(np.float32))
    paths.meta.write_text(json.dumps(meta, indent=2))
    paths.timeline.write_text(json.dumps(timeline, indent=2))
    paths.summary.write_text(json.dumps(_timeline_summary(timeline), indent=2))


def ensure_static_bundle(scenario_id: str) -> BundlePaths:
    ensure_static_catalog()
    rainfall_path = RAINFALL_DIR / f"{scenario_id}.csv"
    if not rainfall_path.exists():
        raise FileNotFoundError(f"Unknown static scenario: {scenario_id}")

    root = STATIC_SCENARIO_DIR / scenario_id
    paths = _bundle_paths(root)
    if (paths.peak_map.exists() or paths.depth_frames.exists()) and paths.meta.exists() and paths.timeline.exists() and paths.summary.exists():
        try:
            meta = json.loads(paths.meta.read_text())
            if meta.get("asset_version") == STATIC_BUNDLE_VERSION:
                return paths
        except json.JSONDecodeError:
            pass

    rainfall = _read_rainfall_csv(rainfall_path)
    meta = _bundle_meta("static", scenario_id, len(rainfall))
    meta.update(
        {
            "scenario_id": scenario_id,
            "title": _scenario_display_name(scenario_id),
            "family": _scenario_family(scenario_id),
            "total_rainfall_mm": round(sum(rainfall), 3),
        }
    )
    peak_map = _scenario_peak_map(scenario_id)
    timeline = _build_static_timeline(peak_map, rainfall, int(meta["timestep_minutes"]))
    _write_static_bundle(paths, meta, peak_map, timeline)
    logger.info("Built static scenario bundle for %s", scenario_id)
    return paths


def load_bundle_json(paths: BundlePaths) -> Dict[str, object]:
    return {
        "meta": json.loads(paths.meta.read_text()),
        "timeline": json.loads(paths.timeline.read_text()),
        "summary": json.loads(paths.summary.read_text()),
    }


def render_bundle_layer(paths: BundlePaths, layer_name: str, frame_idx: int) -> Path:
    output = paths.layers_dir / layer_name / f"t{frame_idx:03d}.png"

    if paths.peak_map.exists():
        peak = np.load(paths.peak_map)["peak"]
        timeline = json.loads(paths.timeline.read_text())
        scale = float(timeline[frame_idx].get("scale", 0.0))
        depth = peak * scale
    elif paths.depth_frames.exists():
        arrays = np.load(paths.depth_frames)
        depth = arrays["depth"][frame_idx]
    else:
        raise FileNotFoundError(f"No depth source found for bundle {paths.root}")
    if layer_name == "water_depth" and paths.peak_map.exists():
        rgba = _render_temporal_depth_rgba(depth, peak, scale)
    else:
        rgba = _render_rgba(depth, layer_name)
    _save_png(rgba, output)
    return output


def create_dynamic_run(rainfall_hourly: List[float], hours: int, timestep_minutes: int, run_label: Optional[str]) -> str:
    ensure_app_dirs()
    run_id = uuid4().hex[:10]
    paths = _bundle_paths(DYNAMIC_RUN_DIR / run_id)
    meta = _bundle_meta("dynamic", run_id, hours)
    trimmed_rainfall = [float(value) for value in rainfall_hourly[:hours]]
    total_rainfall = float(sum(trimmed_rainfall))
    family = "block" if max(trimmed_rainfall or [0.0]) > max(total_rainfall / max(hours, 1), 1.0) * 1.8 else "random"
    scenario_id = f"{family}_{int(min(max(round(total_rainfall / 50.0) * 50.0, 200.0), 350.0))}"
    peak_map = _scenario_peak_map(scenario_id)
    if total_rainfall > 0:
        peak_map = peak_map * (total_rainfall / float(scenario_id.rsplit('_', 1)[1]))
    timeline = _build_static_timeline(peak_map, trimmed_rainfall, timestep_minutes)
    meta.update(
        {
            "run_id": run_id,
            "title": run_label or f"Dynamic Run {run_id}",
            "hours": hours,
            "rainfall_hourly": trimmed_rainfall,
            "family": family,
            "template_scenario": scenario_id,
            "generation_mode": "live_preview",
        }
    )
    _write_static_bundle(paths, meta, peak_map, timeline)

    alert_engine = AlertEngine(cell_size_m=get_city_profile().cell_size_m)
    peak_idx = 0
    peak_depth = -1.0
    alerts: List[Dict[str, object]] = []
    peak = np.load(paths.peak_map)["peak"]
    for idx, frame in enumerate(timeline):
        if frame["max_depth_m"] > peak_depth:
            peak_depth = frame["max_depth_m"]
            peak_idx = idx
        depth = peak * float(frame.get("scale", 0.0))
        alert = alert_engine.evaluate_depth_frame(depth, int(frame["minutes_from_start"]))
        if alert is not None:
            alerts.append(alert.to_dict())
    (paths.root / "alerts.json").write_text(json.dumps(alerts, indent=2))
    summary = json.loads(paths.summary.read_text())
    summary["peak_frame"] = peak_idx
    paths.summary.write_text(json.dumps(summary, indent=2))
    logger.info("Created dynamic run %s", run_id)
    return run_id


def get_dynamic_bundle(run_id: str) -> BundlePaths:
    paths = _bundle_paths(DYNAMIC_RUN_DIR / run_id)
    if not paths.root.exists():
        raise FileNotFoundError(f"Unknown run_id: {run_id}")
    return paths
