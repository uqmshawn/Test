"""Tests for location_util.py functions."""

import pytest
from src.location_util import (
    Location,
    GpsData,
    LocationComparisonResult,
    calculate_distance,
    dynamic_distance_threshold,
    location_is_different,
)


def test_calculate_distance() -> None:
    """Test distance calculation between two locations."""
    # Arrange
    location1: Location = {"lat": 45.0, "lng": -122.0}
    location2: Location = {"lat": 45.0, "lng": -122.1}  # About 7.9km away

    # Act
    distance = calculate_distance(location1, location2)

    # Assert
    assert isinstance(distance, float)
    assert distance > 0
    assert abs(distance - 7885) < 100  # Allow some margin for geodesic calculation


def test_calculate_distance_same_location() -> None:
    """Test distance calculation between same location."""
    # Arrange
    location: Location = {"lat": 45.0, "lng": -122.0}

    # Act
    distance = calculate_distance(location, location)

    # Assert
    assert distance == 0.0


def test_dynamic_distance_threshold_base() -> None:
    """Test dynamic distance threshold with base PDOP."""
    # Arrange
    pdop = 1.0

    # Act
    threshold = dynamic_distance_threshold(pdop)

    # Assert
    assert threshold == 5.0  # BASE_DISTANCE_THRESHOLD


def test_dynamic_distance_threshold_high() -> None:
    """Test dynamic distance threshold with high PDOP."""
    # Arrange
    pdop = 10.0

    # Act
    threshold = dynamic_distance_threshold(pdop)

    # Assert
    assert threshold == 20.0  # MAX_DISTANCE_THRESHOLD


def test_location_is_different_speed() -> None:
    """Test location difference detection based on speed change."""
    # Arrange
    gps1: GpsData = {"lat": 45.0, "lng": -122.0, "spd": 0.0, "acc": 1.0}
    gps2: GpsData = {
        "lat": 45.0,
        "lng": -122.0,
        "spd": 1.0,
        "acc": 1.0,
    }  # 1 m/s difference

    # Act
    result = location_is_different(gps1, gps2)

    # Assert
    assert result.is_different is True
    assert len(result.reasons) == 1
    assert "Speed changed by" in result.reasons[0]


def test_location_is_different_accuracy() -> None:
    """Test location difference detection based on accuracy (PDOP) change."""
    # Arrange
    gps1: GpsData = {"lat": 45.0, "lng": -122.0, "spd": 0.0, "acc": 1.0}
    gps2: GpsData = {
        "lat": 45.0,
        "lng": -122.0,
        "spd": 0.0,
        "acc": 5.0,
    }  # 4.0 PDOP difference

    # Act
    result = location_is_different(gps1, gps2)

    # Assert
    assert result.is_different is True
    assert len(result.reasons) == 1
    assert "Accuracy (PDOP) changed by" in result.reasons[0]


def test_location_is_different_distance() -> None:
    """Test location difference detection based on distance moved."""
    # Arrange
    gps1: GpsData = {"lat": 45.0, "lng": -122.0, "spd": 0.0, "acc": 1.0}
    gps2: GpsData = {
        "lat": 45.0001,
        "lng": -122.0,
        "spd": 0.0,
        "acc": 1.0,
    }  # About 11m away

    # Act
    result = location_is_different(gps1, gps2)

    # Assert
    assert result.is_different is True
    assert len(result.reasons) == 1
    assert "Distance moved" in result.reasons[0]


def test_location_is_different_no_change() -> None:
    """Test location difference detection with no significant changes."""
    # Arrange
    gps1: GpsData = {"lat": 45.0, "lng": -122.0, "spd": 0.0, "acc": 1.0}
    gps2: GpsData = {
        "lat": 45.0,
        "lng": -122.0,
        "spd": 0.1,
        "acc": 1.1,
    }  # Small changes

    # Act
    result = location_is_different(gps1, gps2)

    # Assert
    assert result.is_different is False
    assert len(result.reasons) == 0


def test_location_is_different_multiple_changes() -> None:
    """Test location difference detection with multiple significant changes."""
    # Arrange
    gps1: GpsData = {"lat": 45.0, "lng": -122.0, "spd": 0.0, "acc": 1.0}
    gps2: GpsData = {
        "lat": 45.0003,  # Distance change (about 33m)
        "lng": -122.0,
        "spd": 1.0,  # Speed change
        "acc": 4.0,  # Accuracy change (threshold will be 20m)
    }

    # Act
    result = location_is_different(gps1, gps2)

    # Assert
    assert result.is_different is True
    assert len(result.reasons) == 3  # Should detect all three changes
