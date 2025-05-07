"""Utility module for location-based calculations and comparisons."""

from dataclasses import dataclass, field
from typing import TypedDict, List
from geopy.distance import geodesic  # type: ignore

SPEED_THRESHOLD = 0.278  # m/s change to be significant - 1 km/h
ACCURACY_THRESHOLD = 3  # PDOP change to be significant
BASE_DISTANCE_THRESHOLD = 5  # metres threshold when PDOP is 1
MAX_DISTANCE_THRESHOLD = 20  # metres maximum threshold


@dataclass
class LocationComparisonResult:
    """Holds the result of a location comparison with reasons for differences."""

    is_different: bool
    reasons: List[str] = field(default_factory=list)


class Location(TypedDict):
    """
    A TypedDict representing a geographical location with latitude and longitude.

    Attributes:
        lat (float): The latitude of the location.
        lng (float): The longitude of the location.
    """

    lat: float
    lng: float


class GpsData(TypedDict):
    """
    GpsData is a TypedDict that represents GPS data with the following fields:
    - lat (float): Latitude coordinate.
    - lng (float): Longitude coordinate.
    - spd (float): Speed.
    - acc (float): Accuracy.
    """

    lat: float
    lng: float
    spd: float
    acc: float


def calculate_distance(a: Location, b: Location) -> float:
    """
    Calculate geodesic distance in metres between two locations.
    """
    return float(geodesic((a["lat"], a["lng"]), (b["lat"], b["lng"])).meters)


def dynamic_distance_threshold(pdop: float) -> float:
    """
    Return a dynamic distance threshold based on PDOP.
    A PDOP of 1 yields a 5m threshold. Higher PDOP values increase the threshold linearly,
    but the threshold is capped at MAX_DISTANCE_THRESHOLD.
    """
    threshold = BASE_DISTANCE_THRESHOLD * pdop
    return min(threshold, MAX_DISTANCE_THRESHOLD)


def location_is_different(a: GpsData, b: GpsData) -> LocationComparisonResult:
    """
    Return True if:
      - The speed has changed by at least SPEED_THRESHOLD,
      - The PDOP (acc) has changed by at least ACCURACY_THRESHOLD, or
      - The distance moved exceeds a dynamic threshold based on the worst PDOP,
        capped at MAX_DISTANCE_THRESHOLD.
    """
    result = LocationComparisonResult(is_different=False)

    # Check speed difference
    speed_diff = abs(a["spd"] - b["spd"])
    if speed_diff >= SPEED_THRESHOLD:
        result.is_different = True
        result.reasons.append(f"Speed changed by {speed_diff:.3f} m/s")

    # Check accuracy (PDOP) difference
    acc_diff = abs(a["acc"] - b["acc"])
    if acc_diff >= ACCURACY_THRESHOLD:
        result.is_different = True
        result.reasons.append(f"Accuracy (PDOP) changed by {acc_diff:.1f}")

    # Check distance moved
    threshold = max(
        dynamic_distance_threshold(a["acc"]), dynamic_distance_threshold(b["acc"])
    )
    distance = calculate_distance(a, b)
    if distance >= threshold:
        result.is_different = True
        result.reasons.append(
            f"Distance moved {distance:.1f}m exceeds threshold of {threshold:.1f}m"
        )

    return result
