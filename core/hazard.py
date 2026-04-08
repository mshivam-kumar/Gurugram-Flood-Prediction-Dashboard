"""Depth-derived overlay classifications for dashboard layers."""

from __future__ import annotations

import numpy as np


def classify_hazard(depth: np.ndarray) -> np.ndarray:
    hazard = np.zeros_like(depth, dtype=np.uint8)
    hazard[(depth >= 0.1) & (depth < 0.3)] = 1
    hazard[(depth >= 0.3) & (depth < 0.5)] = 2
    hazard[(depth >= 0.5) & (depth < 1.0)] = 3
    hazard[depth >= 1.0] = 4
    return hazard


def classify_flood_extent(depth: np.ndarray, threshold: float = 0.1) -> np.ndarray:
    return (depth >= threshold).astype(np.uint8)
