"""FastAPI server for the urban flood dashboard prototype."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.schemas import DynamicPredictRequest, HealthResponse, LivePredictRequest
from app.config import (
    APP_DIR,
    ASSETS_DIR,
    STATIC_DIR,
    ensure_app_dirs,
    get_city_profile,
    get_config,
)
from app.core.dashboard_data import (
    create_dynamic_run,
    ensure_static_bundle,
    ensure_static_catalog,
    get_dynamic_bundle,
    load_bundle_json,
    render_bundle_layer,
)
from app.services.weather import fetch_live_rainfall


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("urbanflood-dashboard")


class AppState:
    predictor = None


state = AppState()


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_app_dirs()
    ensure_static_catalog()
    try:
        from app.core.predictor import get_predictor

        state.predictor = get_predictor()
        logger.info("Predictor loaded successfully")
    except Exception as exc:
        logger.warning("Predictor failed to load on startup: %s", exc)
        state.predictor = None
    yield


app = FastAPI(
    title="UrbanFloodExtremes Dashboard",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    city = get_city_profile()
    catalog = ensure_static_catalog()
    predictor_ready = state.predictor is not None and state.predictor._loaded
    return HealthResponse(
        status="healthy" if predictor_ready else "degraded",
        predictor_loaded=predictor_ready,
        model="PG-AR-FNO",
        city=city.city_name,
        grid_shape=city.grid_shape,
        static_scenarios=len(catalog["scenarios"]),
    )


@app.get("/api/static/catalog")
async def static_catalog():
    return ensure_static_catalog()


@app.get("/api/static/scenarios/{scenario_id}/bundle")
async def static_bundle(scenario_id: str):
    paths = ensure_static_bundle(scenario_id)
    return load_bundle_json(paths)


@app.get("/api/static/scenarios/{scenario_id}/layers/{layer_name}/{frame_idx}")
async def static_layer(scenario_id: str, layer_name: str, frame_idx: int):
    paths = ensure_static_bundle(scenario_id)
    bundle = load_bundle_json(paths)
    if layer_name not in bundle["meta"]["available_layers"]:
        raise HTTPException(404, f"Unknown layer: {layer_name}")
    if frame_idx < 0 or frame_idx >= len(bundle["timeline"]):
        raise HTTPException(404, f"Unknown frame index: {frame_idx}")
    file_path = render_bundle_layer(paths, layer_name, frame_idx)
    return FileResponse(file_path, media_type="image/png")


@app.post("/api/dynamic/predict")
async def dynamic_predict(request: DynamicPredictRequest):
    try:
        run_id = create_dynamic_run(
            rainfall_hourly=request.rainfall_hourly,
            hours=request.hours,
            timestep_minutes=request.timestep_minutes,
            run_label=request.run_label,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    paths = get_dynamic_bundle(run_id)
    return {"run_id": run_id, **load_bundle_json(paths)}


@app.get("/api/live/weather")
async def live_weather(hours: int = 12):
    hours = max(1, min(int(hours), 72))
    return fetch_live_rainfall(hours).to_dict()


@app.post("/api/live/predict")
async def live_predict(request: LivePredictRequest):
    weather = fetch_live_rainfall(request.hours)
    try:
        run_id = create_dynamic_run(
            rainfall_hourly=weather.hourly_mm,
            hours=request.hours,
            timestep_minutes=request.timestep_minutes,
            run_label="Live rainfall forecast",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    paths = get_dynamic_bundle(run_id)
    return {"run_id": run_id, "weather": weather.to_dict(), **load_bundle_json(paths)}


@app.get("/api/dynamic/runs/{run_id}/bundle")
async def dynamic_bundle(run_id: str):
    paths = get_dynamic_bundle(run_id)
    bundle = load_bundle_json(paths)
    alerts_path = paths.root / "alerts.json"
    if alerts_path.exists():
        bundle["alerts"] = json.loads(alerts_path.read_text())
    return bundle


@app.get("/api/dynamic/runs/{run_id}/layers/{layer_name}/{frame_idx}")
async def dynamic_layer(run_id: str, layer_name: str, frame_idx: int):
    paths = get_dynamic_bundle(run_id)
    bundle = load_bundle_json(paths)
    if layer_name not in bundle["meta"]["available_layers"]:
        raise HTTPException(404, f"Unknown layer: {layer_name}")
    if frame_idx < 0 or frame_idx >= len(bundle["timeline"]):
        raise HTTPException(404, f"Unknown frame index: {frame_idx}")
    file_path = render_bundle_layer(paths, layer_name, frame_idx)
    return FileResponse(file_path, media_type="image/png")


app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    import uvicorn

    config = get_config()
    uvicorn.run("app.server:app", host=config.host, port=config.port, reload=config.debug)


if __name__ == "__main__":
    main()
