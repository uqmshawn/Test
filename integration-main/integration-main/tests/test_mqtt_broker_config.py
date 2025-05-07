"""Tests for the Configuration class in mqtt_broker.py."""

import pytest
from unittest.mock import MagicMock, patch
import sys

# Create mocks for all required modules
mock_logger_setup = MagicMock()
mock_logger_setup.set_process_name = MagicMock(return_value=None)
sys.modules["logger_setup"] = mock_logger_setup

# Mock the models module
mock_models = MagicMock()
mock_models.Message = MagicMock()
mock_models.Certificate = MagicMock()
mock_models.SessionLocal = MagicMock()
mock_models.DeviceData = MagicMock()
mock_models.OutboundDeviceData = MagicMock()
sys.modules["models"] = mock_models

# Mock other imports
sys.modules["mqtt_utils"] = MagicMock()
sys.modules["settings_util"] = MagicMock()
sys.modules["device_util"] = MagicMock()

from src.mqtt_broker import Configuration


def test_configuration_singleton():
    """Test that Configuration is a singleton."""
    # Reset the singleton instance
    Configuration._instance = None

    # Get two instances
    config1 = Configuration.get_instance()
    config2 = Configuration.get_instance()

    # They should be the same instance
    assert config1 is config2


def test_configuration_direct_instantiation():
    """Test that direct instantiation raises an error."""
    # Reset the singleton instance
    Configuration._instance = None

    # First instantiation through get_instance should work
    config1 = Configuration.get_instance()
    assert config1 is not None

    # Direct instantiation should raise RuntimeError
    with pytest.raises(RuntimeError, match="Use Configuration.get_instance()"):
        Configuration()


def test_configuration_values_changed():
    """Test the _values_changed method."""
    # Reset the singleton instance
    Configuration._instance = None
    config = Configuration.get_instance()

    # Set initial values
    config.iot_env = "dev"
    config.tenant_name = "tenant1"
    config.device_name = "device1"
    config.aws_iot_endpoint = "endpoint1"

    # Test with same values
    settings = {
        "iot_environment": "dev",
        "tenant_name": "tenant1",
        "device_name": "device1",
        "aws_iot_endpoint": "endpoint1",
    }
    assert not config._values_changed(settings)

    # Test with different values
    settings = {
        "iot_environment": "prod",
        "tenant_name": "tenant1",
        "device_name": "device1",
        "aws_iot_endpoint": "endpoint1",
    }
    assert config._values_changed(settings)


def test_configuration_has_required_values():
    """Test the has_required_values method."""
    # Reset the singleton instance
    Configuration._instance = None
    config = Configuration.get_instance()

    # Test with all required values
    settings = {
        "iot_environment": "dev",
        "tenant_name": "tenant1",
        "device_name": "device1",
        "aws_iot_endpoint": "endpoint1",
    }
    assert config.has_required_values(settings)

    # Test with missing values
    settings = {
        "iot_environment": "dev",
        "tenant_name": "tenant1",
        "device_name": "",
        "aws_iot_endpoint": "endpoint1",
    }
    assert not config.has_required_values(settings)

    # Test with empty values
    settings = {
        "iot_environment": "dev",
        "tenant_name": "tenant1",
        "device_name": "device1",
        "aws_iot_endpoint": "",
    }
    assert not config.has_required_values(settings)


def test_configuration_update_from_settings():
    """Test the update_from_settings method."""
    # Reset the singleton instance
    Configuration._instance = None
    config = Configuration.get_instance()

    # Set initial values
    config.iot_env = "dev"
    config.tenant_name = "tenant1"
    config.device_name = "device1"
    config.aws_iot_endpoint = "endpoint1"

    # Test with same values
    settings = {
        "iot_environment": "dev",
        "tenant_name": "tenant1",
        "device_name": "device1",
        "aws_iot_endpoint": "endpoint1",
    }
    assert not config.update_from_settings(settings)

    # Test with different values
    settings = {
        "iot_environment": "prod",
        "tenant_name": "tenant1",
        "device_name": "device1",
        "aws_iot_endpoint": "endpoint1",
    }
    assert config.update_from_settings(settings)
    assert config.iot_env == "prod"

    # Test with missing values
    settings = {
        "iot_environment": "dev",
        "tenant_name": "tenant1",
        "device_name": "",
        "aws_iot_endpoint": "endpoint1",
    }
    assert not config.update_from_settings(settings)
    assert config.iot_env == "prod"  # Should not change
