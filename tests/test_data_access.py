"""Tests for data_access.py functions."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import SQLAlchemyError

from src.data_access import (
    GPSCoordinates,
    _is_valid_gps_data,
    store_gps_coordinates,
    purge_old_messages,
    purge_old_gps_data,
    purge_old_device_data,
)


def test_is_valid_gps_data_valid() -> None:
    """Test GPS data validation with valid data."""
    # Arrange
    valid_gps = GPSCoordinates(
        lat=45.0,
        lng=-122.0,
        alt=100.0,
        spd=50.0,
        heading=90.0,
        pdop=1.0,
        hdop=0.8,
        vdop=0.6,
        loc_ts=1678886400,
    )

    # Act
    result = _is_valid_gps_data(valid_gps)

    # Assert
    assert result is True


def test_is_valid_gps_data_invalid_lat() -> None:
    """Test GPS data validation with invalid latitude."""
    # Arrange
    invalid_gps = GPSCoordinates(
        lat=91.0,  # Invalid latitude
        lng=-122.0,
        alt=100.0,
        spd=50.0,
        heading=90.0,
        pdop=1.0,
        hdop=0.8,
        vdop=0.6,
        loc_ts=1678886400,
    )

    # Act
    result = _is_valid_gps_data(invalid_gps)

    # Assert
    assert result is False


def test_is_valid_gps_data_invalid_lng() -> None:
    """Test GPS data validation with invalid longitude."""
    # Arrange
    invalid_gps = GPSCoordinates(
        lat=45.0,
        lng=181.0,  # Invalid longitude
        alt=100.0,
        spd=50.0,
        heading=90.0,
        pdop=1.0,
        hdop=0.8,
        vdop=0.6,
        loc_ts=1678886400,
    )

    # Act
    result = _is_valid_gps_data(invalid_gps)

    # Assert
    assert result is False


def test_is_valid_gps_data_missing_timestamp() -> None:
    """Test GPS data validation with missing timestamp."""
    # Arrange
    invalid_gps = GPSCoordinates(
        lat=45.0,
        lng=-122.0,
        alt=100.0,
        spd=50.0,
        heading=90.0,
        pdop=1.0,
        hdop=0.8,
        vdop=0.6,
        loc_ts=0,  # Invalid timestamp
    )

    # Act
    result = _is_valid_gps_data(invalid_gps)

    # Assert
    assert result is False


@patch("src.data_access.SessionLocal")
def test_store_gps_coordinates_success(mock_session_local: MagicMock) -> None:
    """Test successful GPS coordinates storage."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session

    valid_gps = GPSCoordinates(
        lat=45.0,
        lng=-122.0,
        alt=100.0,
        spd=50.0,
        heading=90.0,
        pdop=1.0,
        hdop=0.8,
        vdop=0.6,
        loc_ts=1678886400,
    )

    # Act
    store_gps_coordinates(valid_gps)

    # Assert
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_session.rollback.assert_not_called()


@patch("src.data_access.SessionLocal")
def test_store_gps_coordinates_db_error(mock_session_local: MagicMock) -> None:
    """Test GPS coordinates storage with database error."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session
    mock_session.commit.side_effect = SQLAlchemyError("Database error")

    valid_gps = GPSCoordinates(
        lat=45.0,
        lng=-122.0,
        alt=100.0,
        spd=50.0,
        heading=90.0,
        pdop=1.0,
        hdop=0.8,
        vdop=0.6,
        loc_ts=1678886400,
    )

    # Act & Assert
    with pytest.raises(SQLAlchemyError):
        store_gps_coordinates(valid_gps)
    mock_session.rollback.assert_called_once()
    mock_session.commit.assert_called_once()


@patch("src.data_access.SessionLocal")
def test_purge_old_messages_success(mock_session_local: MagicMock) -> None:
    """Test successful message purge."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.delete.return_value = 5  # Simulate deleting 5 records

    # Act
    purge_old_messages(days=7)

    # Assert
    mock_session.commit.assert_called_once()
    mock_session.rollback.assert_not_called()
    mock_query.delete.assert_called_once()


@patch("src.data_access.SessionLocal")
def test_purge_old_gps_data_success(mock_session_local: MagicMock) -> None:
    """Test successful GPS data purge."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session

    # Mock the outbound query
    mock_outbound = MagicMock()
    mock_outbound.last_sent = datetime.now(timezone.utc) - timedelta(days=1)
    mock_session.query.return_value.order_by.return_value.first.return_value = (
        mock_outbound
    )

    # Mock the GPS data query
    mock_gps_query = MagicMock()
    mock_session.query.return_value = mock_gps_query
    mock_gps_query.filter.return_value = mock_gps_query
    mock_gps_query.delete.return_value = 10  # Simulate deleting 10 records

    # Act
    purge_old_gps_data(days=7)

    # Assert
    mock_session.commit.assert_called_once()
    mock_session.rollback.assert_not_called()
    assert (
        mock_session.query.call_count >= 2
    )  # At least 2 queries (outbound and GPS data)


@patch("src.data_access.SessionLocal")
def test_purge_old_device_data_success(mock_session_local: MagicMock) -> None:
    """Test successful device data purge."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session

    # Mock the outbound query
    mock_outbound = MagicMock()
    mock_outbound.last_sent = datetime.now(timezone.utc) - timedelta(days=1)
    mock_session.query.return_value.order_by.return_value.first.return_value = (
        mock_outbound
    )

    # Mock the device data query
    mock_device_query = MagicMock()
    mock_session.query.return_value = mock_device_query
    mock_device_query.filter.return_value = mock_device_query
    mock_device_query.delete.return_value = 8  # Simulate deleting 8 records

    # Act
    purge_old_device_data(days=7)

    # Assert
    mock_session.commit.assert_called_once()
    mock_session.rollback.assert_not_called()
    assert (
        mock_session.query.call_count >= 2
    )  # At least 2 queries (outbound and device data)
