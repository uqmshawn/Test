"""Tests for the device message processing functionality in mqtt_broker.py."""

import pytest
from unittest.mock import MagicMock, patch, create_autospec
import json
from datetime import datetime, timezone
import sys
import re

# Create mocks for all required modules
mock_logger_setup = MagicMock()
mock_logger_setup.set_process_name = MagicMock(return_value=None)
sys.modules["logger_setup"] = mock_logger_setup

# Mock the models module
mock_models = MagicMock()
mock_models.Message = MagicMock
mock_models.Certificate = MagicMock
mock_models.BMSData = MagicMock
mock_models.MultiPlusData = MagicMock


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
from src.mqtt_broker import process_device_message, sanitize_json_payload
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

    # Mock extract_bms_measures and extract_multiplus_measures to return None
    mock_bms_measures = None
    mock_multiplus_measures = None

    # Mock the database query to return no previous data
    mock_session.query.return_value.order_by.return_value.first.return_value = None

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        with patch("src.mqtt_broker.extract_measures", return_value=mock_measures):
            with patch(
                "src.mqtt_broker.extract_bms_measures", return_value=mock_bms_measures
            ):
                with patch(
                    "src.mqtt_broker.extract_multiplus_measures",
                    return_value=mock_multiplus_measures,
                ):
                    with patch("src.mqtt_broker.datetime") as mock_datetime:
                        mock_now = datetime.now(timezone.utc)
                        mock_datetime.now.return_value = mock_now

                        result = process_device_message("out/device", payload)

                        assert result is True
                        # Check that only DeviceData and OutboundDeviceData were added (no BMS or MultiPlus)
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

    # Mock extract_bms_measures and extract_multiplus_measures to return None
    mock_bms_measures = None
    mock_multiplus_measures = None

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
                "src.mqtt_broker.extract_bms_measures", return_value=mock_bms_measures
            ):
                with patch(
                    "src.mqtt_broker.extract_multiplus_measures",
                    return_value=mock_multiplus_measures,
                ):
                    with patch(
                        "src.mqtt_broker.are_measures_different", return_value=mock_diff
                    ):
                        with patch("src.mqtt_broker.datetime") as mock_datetime:
                            mock_now = datetime.now(timezone.utc)
                            mock_datetime.now.return_value = mock_now

                            result = process_device_message("out/device", payload)

                            assert result is True
                            # Check that DeviceData and OutboundDeviceData were added
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

    # Mock extract_bms_measures and extract_multiplus_measures to return None
    mock_bms_measures = None
    mock_multiplus_measures = None

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

    # Mock are_bms_measures_different and are_multiplus_measures_different to match
    mock_bms_diff = ComparisonResult(is_different=False, reasons=[])
    mock_multiplus_diff = ComparisonResult(is_different=False, reasons=[])

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        with patch("src.mqtt_broker.extract_measures", return_value=mock_measures):
            with patch(
                "src.mqtt_broker.extract_bms_measures", return_value=mock_bms_measures
            ):
                with patch(
                    "src.mqtt_broker.extract_multiplus_measures",
                    return_value=mock_multiplus_measures,
                ):
                    with patch(
                        "src.mqtt_broker.are_measures_different", return_value=mock_diff
                    ):
                        with patch(
                            "src.mqtt_broker.are_bms_measures_different",
                            return_value=mock_bms_diff,
                        ):
                            with patch(
                                "src.mqtt_broker.are_multiplus_measures_different",
                                return_value=mock_multiplus_diff,
                            ):
                                with patch("src.mqtt_broker.datetime") as mock_datetime:
                                    mock_now = datetime.now(timezone.utc)
                                    mock_datetime.now.return_value = mock_now

                                    result = process_device_message(
                                        "out/device", payload
                                    )

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


def test_process_device_message_with_bms_data(mock_session):
    """Test process_device_message with BMS data."""
    # Create test data with BMS
    payload = json.dumps(
        {
            "device": {
                "timestamp": "2023-01-01T00:00:00Z",
                "bms": {
                    "volts": 48.2,
                    "amps": 15.7,
                    "watts": 756.74,
                    "remainingAh": 180.5,
                    "fullAh": 200.0,
                    "charging": True,
                    "temp": 32.5,
                    "stateOfCharge": 90.25,
                    "stateOfHealth": 98.5,
                },
            }
        }
    )

    # Mock extract_measures to return empty
    mock_measures = {}

    # Mock BMS data
    mock_bms_measures = {
        "volts": 48.2,
        "amps": 15.7,
        "watts": 756.74,
        "remainingAh": 180.5,
        "fullAh": 200.0,
        "charging": True,
        "temp": 32.5,
        "stateOfCharge": 90.25,
        "stateOfHealth": 98.5,
    }

    # No MultiPlus data
    mock_multiplus_measures = None

    # Mock the database query to return no previous data
    mock_session.query.return_value.order_by.return_value.first.return_value = None

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        with patch("src.mqtt_broker.extract_measures", return_value=mock_measures):
            with patch(
                "src.mqtt_broker.extract_bms_measures", return_value=mock_bms_measures
            ):
                with patch(
                    "src.mqtt_broker.extract_multiplus_measures",
                    return_value=mock_multiplus_measures,
                ):
                    with patch("src.mqtt_broker.datetime") as mock_datetime:
                        mock_now = datetime.now(timezone.utc)
                        mock_datetime.now.return_value = mock_now

                        result = process_device_message("out/device", payload)

                        assert result is True
                        # DeviceData, BMSData, and OutboundDeviceData
                        assert mock_session.add.call_count == 3
                        mock_session.commit.assert_called_once()


def test_process_device_message_with_multiplus_data(mock_session):
    """Test process_device_message with MultiPlus data."""
    # Create test data with MultiPlus
    payload = json.dumps(
        {
            "device": {
                "timestamp": "2023-01-01T00:00:00Z",
                "multiPlus": {
                    "voltsIn": 230.5,
                    "ampsIn": 4.2,
                    "wattsIn": 968.1,
                    "freqIn": 50.02,
                    "voltsOut": 230.0,
                    "ampsOut": 3.8,
                    "wattsOut": 874.0,
                    "freqOut": 50.0,
                },
            }
        }
    )

    # Mock extract_measures to return empty
    mock_measures = {}

    # No BMS data
    mock_bms_measures = None

    # Mock MultiPlus data
    mock_multiplus_measures = {
        "voltsIn": 230.5,
        "ampsIn": 4.2,
        "wattsIn": 968.1,
        "freqIn": 50.02,
        "voltsOut": 230.0,
        "ampsOut": 3.8,
        "wattsOut": 874.0,
        "freqOut": 50.0,
    }

    # Mock the database query to return no previous data
    mock_session.query.return_value.order_by.return_value.first.return_value = None

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        with patch("src.mqtt_broker.extract_measures", return_value=mock_measures):
            with patch(
                "src.mqtt_broker.extract_bms_measures", return_value=mock_bms_measures
            ):
                with patch(
                    "src.mqtt_broker.extract_multiplus_measures",
                    return_value=mock_multiplus_measures,
                ):
                    with patch("src.mqtt_broker.datetime") as mock_datetime:
                        mock_now = datetime.now(timezone.utc)
                        mock_datetime.now.return_value = mock_now

                        result = process_device_message("out/device", payload)

                        assert result is True
                        # DeviceData, MultiPlusData, and OutboundDeviceData
                        assert mock_session.add.call_count == 3
                        mock_session.commit.assert_called_once()


def test_sanitize_json_payload_no_nan():
    """Test sanitize_json_payload with no #NaN values."""
    payload = json.dumps(
        {
            "device": {
                "timestamp": "2023-01-01T00:00:00Z",
                "bms": {
                    "volts": 48.2,
                    "amps": 15.7,
                    "watts": 756.74,
                },
            }
        }
    )

    sanitized, was_modified = sanitize_json_payload(payload)

    assert was_modified is False
    assert sanitized == payload


def test_sanitize_json_payload_with_nan():
    """Test sanitize_json_payload with #NaN values."""
    payload = json.dumps(
        {
            "device": {
                "timestamp": "2023-01-01T00:00:00Z",
                "bms": {
                    "volts": 48.2,
                    "amps": "#NaN",
                    "watts": 756.74,
                },
            }
        }
    )

    # Replace the double quotes around #NaN with nothing to simulate the actual format
    payload = payload.replace('"#NaN"', "#NaN")

    with patch("logging.warning") as mock_warning:
        sanitized, was_modified = sanitize_json_payload(payload)

        assert was_modified is True
        assert "#NaN" not in sanitized
        assert "null" in sanitized

        # Verify the warning was logged
        mock_warning.assert_called_once()

        # Parse the sanitized JSON to ensure it's valid
        parsed = json.loads(sanitized)
        assert parsed["device"]["bms"]["amps"] is None


def test_sanitize_json_payload_with_multiple_nan():
    """Test sanitize_json_payload with multiple #NaN values."""
    payload = json.dumps(
        {
            "device": {
                "timestamp": "2023-01-01T00:00:00Z",
                "bms": {
                    "volts": "#NaN",
                    "amps": "#NaN",
                    "watts": 756.74,
                },
                "multiPlus": {
                    "voltsIn": "#NaN",
                    "ampsIn": 4.2,
                },
            }
        }
    )

    # Replace the double quotes around #NaN with nothing to simulate the actual format
    payload = payload.replace('"#NaN"', "#NaN")

    with patch("logging.warning") as mock_warning:
        sanitized, was_modified = sanitize_json_payload(payload)

        assert was_modified is True
        assert "#NaN" not in sanitized
        assert "null" in sanitized

        # Verify the warning was logged with the correct count
        mock_warning.assert_called_once_with(
            "Found and replaced %d #NaN value(s) in JSON payload with null", 3
        )

        # Parse the sanitized JSON to ensure it's valid
        parsed = json.loads(sanitized)
        assert parsed["device"]["bms"]["volts"] is None
        assert parsed["device"]["bms"]["amps"] is None
        assert parsed["device"]["multiPlus"]["voltsIn"] is None
        assert abs(parsed["device"]["bms"]["watts"] - 756.74) < 0.001
        assert abs(parsed["device"]["multiPlus"]["ampsIn"] - 4.2) < 0.001


def test_sanitize_json_payload_with_both_quoted_and_unquoted_nan():
    """Test sanitize_json_payload with both quoted and unquoted #NaN values."""
    # Create a payload with both quoted and unquoted #NaN values
    # Start with a normal JSON structure
    payload_dict = {
        "device": {
            "timestamp": "2023-01-01T00:00:00Z",
            "bms": {
                "volts": "#NaN",  # This will be quoted by json.dumps
                "amps": 15.7,
                "watts": 756.74,
            },
            "multiPlus": {
                "voltsIn": 230.5,
                "ampsOut": "#NaN",  # This will be quoted by json.dumps
            },
        }
    }

    # Convert to JSON string
    payload = json.dumps(payload_dict)

    # Manually add an unquoted #NaN value (this simulates malformed JSON that might be received)
    # We'll replace one of the quoted values with unquoted and leave the other quoted
    payload = payload.replace('"#NaN"', "#NaN", 1)  # Replace only the first occurrence

    with patch("logging.warning") as mock_warning:
        sanitized, was_modified = sanitize_json_payload(payload)

        assert was_modified is True
        assert "#NaN" not in sanitized
        assert "null" in sanitized

        # Verify the warning was logged with the correct count (should be 2)
        mock_warning.assert_called_once_with(
            "Found and replaced %d #NaN value(s) in JSON payload with null", 2
        )

        # Parse the sanitized JSON to ensure it's valid
        parsed = json.loads(sanitized)
        assert parsed["device"]["bms"]["volts"] is None
        assert parsed["device"]["multiPlus"]["ampsOut"] is None
        assert abs(parsed["device"]["bms"]["amps"] - 15.7) < 0.001
        assert abs(parsed["device"]["multiPlus"]["voltsIn"] - 230.5) < 0.001


def test_process_device_message_with_nan_values(mock_session):
    """Test process_device_message with #NaN values in the payload."""
    # Create test data with #NaN values
    payload_dict = {
        "device": {
            "timestamp": "2023-01-01T00:00:00Z",
            "bms": {
                "volts": 48.2,
                "amps": "#NaN",  # This will be replaced with null
                "watts": 756.74,
                "remainingAh": 180.5,
                "fullAh": 200.0,
                "charging": True,
                "temp": 32.5,
                "stateOfCharge": 90.25,
                "stateOfHealth": 98.5,
            },
        }
    }

    payload = json.dumps(payload_dict)
    # Replace the double quotes around #NaN with nothing to simulate the actual format
    payload = payload.replace('"#NaN"', "#NaN")

    # Mock extract_measures to return a valid object
    mock_measures = {"pwr": 1, "tankPct": 75.0}

    # Mock BMS data with the null value properly handled
    mock_bms_measures = {
        "volts": 48.2,
        "amps": 0,  # The sanitized value should be converted to 0 by the extract_bms_measures function
        "watts": 756.74,
        "remainingAh": 180.5,
        "fullAh": 200.0,
        "charging": True,
        "temp": 32.5,
        "stateOfCharge": 90.25,
        "stateOfHealth": 98.5,
    }

    # No MultiPlus data
    mock_multiplus_measures = None

    # Mock the database query to return no previous data
    mock_session.query.return_value.order_by.return_value.first.return_value = None

    with patch("logging.warning") as mock_warning:
        with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
            with patch("src.mqtt_broker.extract_measures", return_value=mock_measures):
                with patch(
                    "src.mqtt_broker.extract_bms_measures",
                    return_value=mock_bms_measures,
                ):
                    with patch(
                        "src.mqtt_broker.extract_multiplus_measures",
                        return_value=mock_multiplus_measures,
                    ):
                        with patch("src.mqtt_broker.datetime") as mock_datetime:
                            mock_now = datetime.now(timezone.utc)
                            mock_datetime.now.return_value = mock_now

                            result = process_device_message("out/device", payload)

                            # Verify the warning was logged
                            mock_warning.assert_called_once()

                            assert result is True
                            # DeviceData, BMSData, and OutboundDeviceData
                            assert mock_session.add.call_count == 3
                            mock_session.commit.assert_called_once()
