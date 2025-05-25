"""Tests for background_task.py vehicle data-related functions."""

import pytest
from unittest.mock import MagicMock, patch, call
import paho.mqtt.client as mqtt
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import time

from src.background_task import (
    vehicle_data_polling_wrapper,
    _get_last_outbound_vehicle_data,
    _handle_vehicle_heartbeat,
    process_vehicle_outbound,
    start_vehicle_outbound_thread,
)
from src.models import VehicleData, OutboundVehicleData


@patch("src.background_task.time")
@patch("src.background_task.SessionLocal")
@patch("src.background_task.vdu.fetch_router_vehicle_data")
@patch("src.background_task.vdu.parse_vehicle_data")
@patch("src.background_task.vdu.should_store_vehicle_data")
@patch("src.background_task.vdu.store_vehicle_data")
@patch("src.background_task.vdu.log_new_vehicle_data")
def test_vehicle_data_polling_wrapper(
    mock_log_data,
    mock_store_data,
    mock_should_store,
    mock_parse_data,
    mock_fetch_vehicle,
    mock_session,
    mock_time,
):
    # Setup test data
    router_ip = "192.168.1.1"
    credentials = {"username": "test", "password": "test"}
    session = mock_session()

    # Setup counter to break the loop
    call_count = 0

    def mock_sleep(seconds):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:  # Break after second iteration
            raise KeyboardInterrupt()

    mock_time.sleep.side_effect = mock_sleep

    # Setup mock returns
    raw_data = {"some": "data"}
    parsed_data = {"parsed": "data"}
    mock_fetch_vehicle.return_value = (
        session,
        raw_data,
    )  # Return tuple of session and data
    mock_parse_data.return_value = parsed_data
    mock_should_store.side_effect = [
        True,
        False,
    ]  # First call returns True, second call returns False
    mock_store_data.return_value = parsed_data

    # Run the function
    try:
        vehicle_data_polling_wrapper(router_ip, session, credentials)
    except KeyboardInterrupt:
        pass  # Expected to break the loop

    # Verify the function behavior
    assert mock_fetch_vehicle.call_count == 2
    mock_fetch_vehicle.assert_called_with(session, router_ip, credentials)
    mock_parse_data.assert_called_with(raw_data)

    # First call should check with no last_vehicle_data
    mock_should_store.assert_has_calls(
        [
            call(parsed_data, None),  # First call with no last_vehicle_data
            call(
                parsed_data, parsed_data
            ),  # Second call with last_vehicle_data from first call
        ]
    )

    # Store and log should only be called once since second should_store returns False
    mock_store_data.assert_called_once_with(parsed_data)
    mock_log_data.assert_called_once_with(parsed_data)
    assert mock_time.sleep.call_count == 2
    mock_time.sleep.assert_called_with(5)


@patch("src.background_task.SessionLocal")
def test_get_last_outbound_vehicle_data(mock_session_local: MagicMock) -> None:
    """Test getting last outbound vehicle data."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.first.return_value = None
    mock_query.filter.return_value = mock_query
    mock_query.all.return_value = []

    # Act
    last_outbound, records = _get_last_outbound_vehicle_data()

    # Assert
    assert last_outbound is None
    assert records == []
    mock_session.query.assert_called()


def test_handle_vehicle_heartbeat_no_last_outbound() -> None:
    """Test vehicle heartbeat handling with no last outbound data."""
    # Arrange
    last_outbound = None
    vehicle_records = []

    # Act
    result = _handle_vehicle_heartbeat(last_outbound, vehicle_records)

    # Assert
    assert result is None


@patch("src.background_task.vdu.create_vehicle_payload")
def test_handle_vehicle_heartbeat_with_data(mock_create_payload: MagicMock) -> None:
    """Test vehicle heartbeat handling with existing data."""
    # Arrange
    last_outbound = MagicMock(spec=OutboundVehicleData)
    last_outbound.last_sent = datetime.now(timezone.utc) - timedelta(
        hours=2
    )  # 2 hours ago

    # Create a proper mock of VehicleData with required attributes
    vehicle_data = VehicleData()
    vehicle_data.timestamp = datetime.now(timezone.utc)
    vehicle_data.ign_enabled = True
    vehicle_data.ign_state = True
    vehicle_data.io_enabled = True
    vehicle_data.io_state = True
    vehicle_records = [vehicle_data]

    # Set up mock payload
    mock_create_payload.return_value = {"test": "payload"}

    # Act
    result = _handle_vehicle_heartbeat(last_outbound, vehicle_records)

    # Assert
    assert result is not None
    assert result == {"test": "payload"}
    mock_create_payload.assert_called_once_with(vehicle_data)


@patch("src.background_task.vdu.detect_vehicle_data_changes")
@patch("src.background_task.vdu.create_vehicle_payload")
@patch("src.background_task._get_last_outbound_vehicle_data")
@patch("src.background_task._handle_vehicle_heartbeat")
def test_process_vehicle_outbound(
    mock_handle_heartbeat: MagicMock,
    mock_get_last_outbound: MagicMock,
    mock_create_payload: MagicMock,
    mock_detect_changes: MagicMock,
) -> None:
    """Test processing vehicle outbound data."""
    # Arrange
    client = MagicMock(spec=mqtt.Client)
    vehicle_data = VehicleData()
    vehicle_data.timestamp = datetime.now(timezone.utc)
    mock_get_last_outbound.return_value = (
        None,
        [vehicle_data],
    )  # No last outbound, one record

    # Setup mock returns for the case where we have no last outbound
    mock_detect_changes.return_value = []  # No changes detected
    mock_create_payload.return_value = {"test": "payload"}

    # Act
    process_vehicle_outbound(client)

    # Assert
    mock_get_last_outbound.assert_called_once()
    mock_detect_changes.assert_called_once()
    mock_create_payload.assert_called_once_with(
        vehicle_data
    )  # Should create payload from latest record
    client.publish.assert_called_once()


@pytest.mark.timeout(5)  # 5 second timeout
@patch("src.background_task.logging")
@patch("src.background_task.time.sleep")
@patch("src.background_task.process_vehicle_outbound")
def test_start_vehicle_outbound_thread(
    mock_process_vehicle: MagicMock,
    mock_sleep: MagicMock,
    mock_logging: MagicMock,
) -> None:
    """Test starting the vehicle outbound thread."""
    # Arrange
    client = MagicMock(spec=mqtt.Client)

    # Set up mock to do nothing (don't raise exception)
    mock_process_vehicle.return_value = None
    mock_sleep.side_effect = lambda x: None  # Don't actually sleep

    # Act
    thread = start_vehicle_outbound_thread(client)

    # Give the thread a moment to start and run
    time.sleep(0.1)  # Small sleep to let thread start

    # Assert
    assert thread.is_alive()  # Thread should be running
    assert thread.daemon  # Thread should be a daemon thread
    assert thread.name == "vehicle_outbound_thread"  # Check thread name
    assert hasattr(thread, "stop_event")  # Check stop event exists

    # Verify the thread is working
    mock_process_vehicle.assert_called_with(client)

    # Clean up
    thread.stop_event.set()  # type: ignore
    thread.join(timeout=1.0)  # Wait for thread to finish
