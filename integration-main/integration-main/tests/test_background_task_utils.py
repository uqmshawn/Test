"""Tests for background_task.py utility and cleanup functions."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import threading
import time
import requests
import socket

from src.background_task import (
    get_timestamp,
    start_cleanup_thread,
    obtain_router_session,
    run_background_task,
)


def test_get_timestamp() -> None:
    """Test timestamp generation."""
    # Act
    timestamp = get_timestamp()

    # Assert
    assert isinstance(timestamp, str)
    # Verify it's a valid UTC timestamp
    assert timestamp.endswith(" UTC")  # Check UTC suffix
    # Parse the timestamp without the UTC suffix
    datetime.strptime(timestamp[:-4], "%Y-%m-%d %H:%M:%S")


@pytest.mark.timeout(5)  # 5 second timeout
@patch("src.background_task.purge_old_messages")
@patch("src.background_task.purge_old_gps_data")
@patch("src.background_task.purge_old_device_data")
@patch("src.background_task.time.sleep")
def test_start_cleanup_thread(
    mock_sleep: MagicMock,
    mock_purge_device: MagicMock,
    mock_purge_gps: MagicMock,
    mock_purge_messages: MagicMock,
) -> None:
    """Test starting the cleanup thread."""
    # Arrange
    cleanup_thread = None

    try:
        # Act
        cleanup_thread = start_cleanup_thread()

        # Assert
        assert cleanup_thread is not None
        assert cleanup_thread.is_alive()
        assert cleanup_thread.name == "cleanup_thread"
        assert hasattr(cleanup_thread, "stop_event")  # Verify stop_event exists

        # Give it a moment to run
        time.sleep(0.1)

        # Verify cleanup functions were called
        mock_purge_messages.assert_called()
        mock_purge_gps.assert_called()
        mock_purge_device.assert_called()

    finally:
        # Signal the thread to stop via the event
        if cleanup_thread and hasattr(cleanup_thread, "stop_event"):
            cleanup_thread.stop_event.set()  # type: ignore
            cleanup_thread.join(timeout=1.0)  # Wait for thread to finish


@pytest.mark.timeout(5)  # 5 second timeout
@patch("src.background_task.router_login")
@patch("src.background_task.load_secrets")
@patch("src.background_task.time.sleep")
def test_obtain_router_session(
    mock_sleep: MagicMock,
    mock_load_secrets: MagicMock,
    mock_router_login: MagicMock,
) -> None:
    """Test obtaining a router session."""
    # Arrange
    mock_secrets = {
        "router_ip": "192.168.1.1",
        "router_userid": "admin",
        "router_password": "pw",
    }
    mock_load_secrets.return_value = {"peplink_api": mock_secrets}
    mock_session = MagicMock()
    # Ensure router_login succeeds immediately
    mock_router_login.return_value = mock_session
    mock_router_login.side_effect = None  # Clear any previous side effects

    # Act
    router_ip, session, credentials = obtain_router_session(
        max_retries=1, retry_delay=0
    )

    # Assert
    assert router_ip == "192.168.1.1"
    assert session == mock_session
    assert credentials == {"router_userid": "admin", "router_password": "pw"}
    mock_load_secrets.assert_called_once()
    mock_router_login.assert_called_once_with("192.168.1.1", "admin", "pw")


@pytest.mark.timeout(5)  # 5 second timeout
@patch("src.background_task.router_login")
@patch("src.background_task.load_secrets")
@patch("src.background_task.time.sleep")
def test_obtain_router_session_retry_then_success(
    mock_sleep: MagicMock,
    mock_load_secrets: MagicMock,
    mock_router_login: MagicMock,
) -> None:
    """Test obtaining a router session with initial failure then success."""
    # Arrange
    mock_secrets = {
        "router_ip": "192.168.1.1",
        "router_userid": "admin",
        "router_password": "pw",
    }
    mock_load_secrets.return_value = {"peplink_api": mock_secrets}
    mock_session = MagicMock()

    # Simulate one failure then success
    mock_router_login.side_effect = [
        requests.exceptions.RequestException("Connection failed"),
        mock_session,
    ]

    # Act
    router_ip, session, credentials = obtain_router_session(
        max_retries=2, retry_delay=0
    )

    # Assert
    assert router_ip == "192.168.1.1"
    assert session == mock_session
    assert credentials == {"router_userid": "admin", "router_password": "pw"}
    assert mock_router_login.call_count == 2  # Called twice due to retry
    assert mock_load_secrets.call_count == 2  # Called twice due to retry


@pytest.mark.timeout(5)  # 5 second timeout
@patch("src.background_task.router_login")
@patch("src.background_task.load_secrets")
@patch("src.background_task.time.sleep")
def test_obtain_router_session_all_retries_fail(
    mock_sleep: MagicMock,
    mock_load_secrets: MagicMock,
    mock_router_login: MagicMock,
) -> None:
    """Test obtaining a router session when all retries fail."""
    # Arrange
    mock_secrets = {
        "router_ip": "192.168.1.1",
        "router_userid": "admin",
        "router_password": "pw",
    }
    mock_load_secrets.return_value = {"peplink_api": mock_secrets}

    # Simulate all attempts failing
    mock_router_login.side_effect = requests.exceptions.RequestException(
        "Connection failed"
    )

    # Act
    router_ip, session, credentials = obtain_router_session(
        max_retries=2, retry_delay=0
    )

    # Assert
    assert router_ip == ""
    assert session is None
    assert not credentials
    assert mock_router_login.call_count == 2  # Called twice due to retry
    assert mock_load_secrets.call_count == 2  # Called twice due to retry


@pytest.mark.timeout(5)  # 5 second timeout
@patch("src.background_task.router_login")
@patch("src.background_task.load_secrets")
@patch("src.background_task.time.sleep")
def test_obtain_router_session_missing_secrets(
    mock_sleep: MagicMock,
    mock_load_secrets: MagicMock,
    mock_router_login: MagicMock,
) -> None:
    """Test obtaining a router session when secrets are missing."""
    # Arrange
    mock_load_secrets.return_value = {"peplink_api": {}}  # Empty secrets

    # Act
    router_ip, session, credentials = obtain_router_session(
        max_retries=1, retry_delay=0
    )

    # Assert
    assert router_ip == ""
    assert session is None
    assert not credentials
    mock_load_secrets.assert_called_once()
    mock_router_login.assert_not_called()  # Should not attempt login with missing secrets


@pytest.mark.timeout(5)  # 5 second timeout
@patch("src.background_task.threading.Thread")
@patch("src.background_task.obtain_router_session")
@patch("src.background_task.start_gps_outbound_thread")
@patch("src.background_task.start_vehicle_outbound_thread")
@patch("src.background_task.start_cleanup_thread")
@patch("src.background_task.time.sleep")
@patch("src.background_task.init_mqtt_client")
def test_run_background_task(
    mock_init_mqtt: MagicMock,
    mock_sleep: MagicMock,
    mock_start_cleanup: MagicMock,
    mock_start_vehicle: MagicMock,
    mock_start_gps: MagicMock,
    mock_obtain_session: MagicMock,
    mock_thread: MagicMock,
) -> None:
    """Test running the background task."""
    # Arrange
    mock_session = MagicMock()
    mock_credentials = {"router_userid": "admin", "router_password": "password"}
    mock_obtain_session.return_value = ("192.168.1.1", mock_session, mock_credentials)
    mock_mqtt_client = MagicMock()
    mock_init_mqtt.return_value = mock_mqtt_client

    # Mock threading.Thread to prevent actual thread creation
    mock_thread_instance = MagicMock()
    mock_thread.return_value = mock_thread_instance

    # Set up mock to break the loop after one iteration
    mock_sleep.side_effect = KeyboardInterrupt()

    # Act
    try:
        run_background_task()
    except KeyboardInterrupt:
        pass  # Expected to break the loop

    # Assert
    mock_obtain_session.assert_called_once()
    mock_init_mqtt.assert_called_once()
    mock_start_gps.assert_called_once_with(mock_mqtt_client)
    mock_start_vehicle.assert_called_once_with(mock_mqtt_client)
    mock_start_cleanup.assert_called_once()

    # Verify that threads were started
    assert mock_thread.call_count >= 2  # At least GPS and vehicle data threads
