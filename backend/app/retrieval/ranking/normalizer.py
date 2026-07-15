import math
from typing import Optional


def min_max_normalize(
    value: float,
    min_val: float = 0.0,
    max_val: float = 1.0,
) -> float:
    if max_val == min_val:
        return 0.5
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def sigmoid_normalize(value: float, midpoint: float = 0.0, steepness: float = 1.0) -> float:
    return 1.0 / (1.0 + math.exp(-steepness * (value - midpoint)))


def z_score_normalize(value: float, mean: float = 0.5, std: float = 0.25) -> float:
    if std <= 0:
        return 0.5
    z = (value - mean) / std
    return max(0.0, min(1.0, 0.5 + z * 0.15))


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


class ScoreNormalizer:
    def __init__(self, method: str = "min_max"):
        self._method = method

    def normalize(self, value: float, **kwargs) -> float:
        if self._method == "min_max":
            return min_max_normalize(value, kwargs.get("min_val", 0.0), kwargs.get("max_val", 1.0))
        elif self._method == "sigmoid":
            return sigmoid_normalize(value, kwargs.get("midpoint", 0.0), kwargs.get("steepness", 1.0))
        elif self._method == "z_score":
            return z_score_normalize(value, kwargs.get("mean", 0.5), kwargs.get("std", 0.25))
        return clamp(value)
