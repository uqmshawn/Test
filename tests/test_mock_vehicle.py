"""Tests for mock_vehicle.py functions."""

import pytest
from unittest.mock import MagicMock, patch
import threading

from src.mock_vehicle import start_mock_vehicle_generator, mock_vehicle_generator


@patch("src.mock_vehicle.vdu.store_vehicle_data")
@patch("src.mock_vehicle.vdu.log_new_vehicle_data")
@patch("src.mock_vehicle.time.sleep")
def test_mock_vehicle_generator(
    mock_sleep: MagicMock, mock_log: MagicMock, mock_store: MagicMock
) -> None:
    """Test that the mock vehicle generator creates the expected data."""
    # Arrange
    mock_store.return_value = MagicMock()  # Simulate successful storage

    # Set up to exit after two iterations
    mock_sleep.side_effect = [None, Exception("Stop test")]

    # Act & Assert
    with pytest.raises(Exception, match="Stop test"):
        mock_vehicle_generator()

    # Verify initial state (ignition ON)
    initial_call = mock_store.call_args_list[0]
    initial_data = initial_call[0][0]
    assert initial_data["ign_enabled"] is True
    assert initial_data["ign_state"] is True
    assert initial_data["io_enabled"] is True

    # Verify updated state (ignition OFF)
    updated_call = mock_store.call_args_list[1]
    updated_data = updated_call[0][0]
    assert updated_data["ign_enabled"] is True
    assert updated_data["ign_state"] is False
    assert updated_data["io_enabled"] is True

    # Verify log calls
    assert mock_log.call_count == 2


@patch("src.mock_vehicle.threading.Thread")
def test_start_mock_vehicle_generator(mock_thread: MagicMock) -> None:
    """Test that the mock vehicle generator thread is started correctly."""
    # Arrange
    mock_thread_instance = MagicMock()
    mock_thread.return_value = mock_thread_instance

    # Act
    result = start_mock_vehicle_generator()

    # Assert
    mock_thread.assert_called_once_with(
        target=mock_vehicle_generator, daemon=True, name="mock_vehicle_thread"
    )
    mock_thread_instance.start.assert_called_once()
    assert result == mock_thread_instance
