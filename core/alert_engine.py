"""Lightweight alert summary derived from flood depth outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np


@dataclass
class FloodAlert:
    alert_id: str
    timestamp: datetime
    severity: str
    headline: str
    description: str
    max_depth_m: float
    affected_area_km2: float
    lead_time_minutes: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "alert_id": self.alert_id,
            "timestamp": self.timestamp.isoformat(),
            "severity": self.severity,
            "headline": self.headline,
            "description": self.description,
            "max_depth_m": round(self.max_depth_m, 3),
            "affected_area_km2": round(self.affected_area_km2, 3),
            "lead_time_minutes": self.lead_time_minutes,
        }


class AlertEngine:
    def __init__(self, cell_size_m: float = 28.48):
        self.cell_area_km2 = (cell_size_m * cell_size_m) / 1e6
        self._history: List[FloodAlert] = []
        self._counter = 0

    def evaluate_depth_frame(self, water_depth: np.ndarray, lead_time_minutes: int) -> Optional[FloodAlert]:
        max_depth = float(water_depth.max())
        flooded_cells = int((water_depth >= 0.1).sum())
        flooded_area_km2 = flooded_cells * self.cell_area_km2
        if max_depth < 0.1 or flooded_cells == 0:
            return None

        severity = "advisory"
        headline = "Localized flooding likely"
        if max_depth >= 1.0:
            severity = "severe"
            headline = "Severe flood depth likely"
        elif max_depth >= 0.5:
            severity = "warning"
            headline = "High flood depth likely"
        elif max_depth >= 0.3:
            severity = "watch"
            headline = "Moderate flood depth likely"

        self._counter += 1
        alert = FloodAlert(
            alert_id=f"UFE-{self._counter:04d}",
            timestamp=datetime.now(),
            severity=severity,
            headline=headline,
            description=(
                f"Predicted peak depth reaches {max_depth:.2f} m with approximately "
                f"{flooded_area_km2:.2f} km^2 affected."
            ),
            max_depth_m=max_depth,
            affected_area_km2=flooded_area_km2,
            lead_time_minutes=lead_time_minutes,
        )
        self._history.append(alert)
        return alert

    def get_history(self) -> List[Dict[str, object]]:
        return [item.to_dict() for item in self._history]
