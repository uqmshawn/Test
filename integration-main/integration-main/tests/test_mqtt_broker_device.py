"""Tests for the device message processing functionality in mqtt_broker.py."""

import pytest
from unittest.mock import MagicMock, patch, create_autospec
import json
from datetime import datetime, timezone
import sys

# Create mocks for all required modules
mock_logger_setup = MagicMock()
mock_logger_setup.set_process_name = MagicMock(return_value=None)
sys.modules["logger_setup"] = mock_logger_setup

# Mock the models module
mock_models = MagicMock()
mock_models.Message = MagicMock
mock_models.Certificate = MagicMock


# Create mock session factory
class MockSession:
    def __init__(self):
        self.add = MagicMock()
        self.commit = MagicMock()
        self.query = MagicMock()
        self.rollback = MagicMock()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


mock_models.SessionLocal = MockSession
sys.modules["models"] = mock_models

# Mock other imports
sys.modules["mqtt_utils"] = MagicMock()
sys.modules["settings_util"] = MagicMock()
sys.modules["device_util"] = MagicMock()

# Now import the mqtt_broker module
from src.mqtt_broker import process_device_message
from src.device_util import ComparisonResult


@pytest.fixture
def mock_session():
    """Create a mock database session."""
    return MockSession()


def test_process_device_message_no_previous_data(mock_session):
    """Test process_device_message with no previous data."""
    # Create test data
    payload = json.dumps(
        {
            "device_id": "test_device",
            "timestamp": "2023-01-01T00:00:00Z",
            "measures": {"temperature": 25.5, "humidity": 60.0},
        }
    )

    # Mock extract_measures to return a known value
    mock_measures = {"temperature": 25.5, "humidity": 60.0}

    # Mock the database query to return no previous data
    mock_session.query.return_value.order_by.return_value.first.return_value = None

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        with patch("src.mqtt_broker.extract_measures", return_value=mock_measures):
            with patch("src.mqtt_broker.datetime") as mock_datetime:
                mock_now = datetime.now(timezone.utc)
                mock_datetime.now.return_value = mock_now

                result = process_device_message("out/device", payload)

                assert result is True
                # Check that both DeviceData and OutboundDeviceData were added
                assert mock_session.add.call_count == 2
                mock_session.commit.assert_called_once()


def test_process_device_message_with_different_measures(mock_session):
    """Test process_device_message with different measures."""
    # Create test data
    payload = json.dumps(
        {
            "device_id": "test_device",
            "timestamp": "2023-01-01T00:00:00Z",
            "measures": {
                "temperature": 26.5,  # Different from previous
                "humidity": 60.0,  # Same as previous
            },
        }
    )

    # Mock extract_measures to return a known value
    mock_measures = {"temperature": 26.5, "humidity": 60.0}

    # Create mock previous data
    mock_previous = MagicMock()
    mock_previous.last_sent = datetime.now(timezone.utc)
    mock_previous.payload = {"measures": {"temperature": 25.5, "humidity": 60.0}}

    # Mock the database query to return previous data
    mock_session.query.return_value.order_by.return_value.first.return_value = (
        mock_previous
    )

    # Mock are_measures_different to return True
    mock_diff = ComparisonResult(is_different=True, reasons=["Temperature changed"])

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        with patch("src.mqtt_broker.extract_measures", return_value=mock_measures):
            with patch(
                "src.mqtt_broker.are_measures_different", return_value=mock_diff
            ):
                with patch("src.mqtt_broker.datetime") as mock_datetime:
                    mock_now = datetime.now(timezone.utc)
                    mock_datetime.now.return_value = mock_now

                    result = process_device_message("out/device", payload)

                    assert result is True
                    # Check that both DeviceData and OutboundDeviceData were added
                    assert mock_session.add.call_count == 2
                    mock_session.commit.assert_called_once()


def test_process_device_message_with_same_measures(mock_session):
    """Test process_device_message with same measures."""
    # Create test data
    payload = json.dumps(
        {
            "device_id": "test_device",
            "timestamp": "2023-01-01T00:00:00Z",
            "measures": {"temperature": 25.5, "humidity": 60.0},
        }
    )

    # Mock extract_measures to return a known value
    mock_measures = {"temperature": 25.5, "humidity": 60.0}

    # Create mock previous data
    mock_previous = MagicMock()
    mock_previous.last_sent = datetime.now(timezone.utc)
    mock_previous.payload = {"measures": {"temperature": 25.5, "humidity": 60.0}}

    # Mock the database query to return previous data
    mock_session.query.return_value.order_by.return_value.first.return_value = (
        mock_previous
    )

    # Mock are_measures_different to return False
    mock_diff = ComparisonResult(is_different=False, reasons=[])

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        with patch("src.mqtt_broker.extract_measures", return_value=mock_measures):
            with patch(
                "src.mqtt_broker.are_measures_different", return_value=mock_diff
            ):
                with patch("src.mqtt_broker.datetime") as mock_datetime:
                    mock_now = datetime.now(timezone.utc)
                    mock_datetime.now.return_value = mock_now

                    result = process_device_message("out/device", payload)

                    assert result is False
                    # Check that only DeviceData was added (no OutboundDeviceData)
                    assert mock_session.add.call_count == 1
                    mock_session.commit.assert_called_once()


def test_process_device_message_with_error(mock_session):
    """Test process_device_message with error."""
    # Create invalid JSON payload
    payload = "invalid json"

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        result = process_device_message("out/device", payload)

        assert result is True  # Should return True on error to be safe
        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_called()
