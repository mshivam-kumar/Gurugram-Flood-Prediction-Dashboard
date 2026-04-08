"""Request and response schemas for the dashboard server."""

from typing import List, Optional

from pydantic import BaseModel, Field


class DynamicPredictRequest(BaseModel):
    rainfall_hourly: List[float] = Field(..., min_length=1, max_length=72)
    hours: int = Field(6, ge=1, le=72)
    timestep_minutes: int = Field(15, ge=5, le=60)
    run_label: Optional[str] = Field(default=None, max_length=120)


class LivePredictRequest(BaseModel):
    hours: int = Field(12, ge=1, le=72)
    timestep_minutes: int = Field(15, ge=5, le=60)


class HealthResponse(BaseModel):
    status: str
    predictor_loaded: bool
    model: str
    city: str
    grid_shape: List[int]
    static_scenarios: int
