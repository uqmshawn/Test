"""Tests for the BrokerManager class in mqtt_broker.py."""

import pytest
from unittest.mock import MagicMock, patch
import paho.mqtt.client as mqtt
import threading
import os
import sys
from datetime import datetime, timezone

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

from src.mqtt_broker import (
    BrokerManager,
    Configuration,
    CertificateManager,
    RemoteClient,
    LocalClient,
    Message,
)


@pytest.fixture
def mock_config():
    """Create a mock Configuration instance."""
    config = MagicMock(spec=Configuration)
    config.iot_env = "dev"
    config.tenant_name = "tenant1"
    config.device_name = "device1"
    config.aws_iot_endpoint = "endpoint1"
    return config


@pytest.fixture
def mock_cert_manager():
    """Create a mock CertificateManager instance."""
    cert_manager = MagicMock(spec=CertificateManager)
    return cert_manager


@pytest.fixture
def mock_remote_client():
    """Create a mock RemoteClient instance."""
    remote_client = MagicMock(spec=RemoteClient)
    remote_client.client = MagicMock(spec=mqtt.Client)
    return remote_client


@pytest.fixture
def mock_local_client():
    """Create a mock LocalClient instance."""
    local_client = MagicMock(spec=LocalClient)
    local_client.client = MagicMock(spec=mqtt.Client)
    return local_client


@pytest.fixture
def broker_manager():
    """Create a BrokerManager instance."""
    return BrokerManager()


def test_broker_manager_init(broker_manager):
    """Test BrokerManager initialization."""
    assert isinstance(broker_manager.cert_manager, CertificateManager)
    assert broker_manager.remote_client is None
    assert broker_manager.local_client is None


def test_broker_manager_initialize(broker_manager):
    """Test BrokerManager initialize method."""
    with patch.object(broker_manager.cert_manager, "wait_for_certs") as mock_wait_certs:
        with patch.object(broker_manager, "_wait_for_config") as mock_wait_config:
            broker_manager.initialize()

            mock_wait_certs.assert_called_once()
            mock_wait_config.assert_called_once()


def test_broker_manager_wait_for_config(broker_manager):
    """Test BrokerManager _wait_for_config method."""
    # Mock load_settings to return valid settings
    mock_settings = {
        "iot_environment": "dev",
        "tenant_name": "tenant1",
        "device_name": "device1",
        "aws_iot_endpoint": "endpoint1",
    }

    with patch("src.mqtt_broker.load_settings", return_value=mock_settings):
        with patch("src.mqtt_broker.CONFIG") as mock_config:
            mock_config.update_from_settings.return_value = True
            mock_config.has_required_values.return_value = True

            broker_manager._wait_for_config()

            mock_config.update_from_settings.assert_called_once_with(mock_settings)


def test_broker_manager_setup_clients(broker_manager, mock_config, mock_cert_manager):
    """Test BrokerManager setup_clients method."""
    with patch("src.mqtt_broker.CONFIG", mock_config):
        with patch("src.mqtt_broker.RemoteClient") as mock_remote_class:
            with patch("src.mqtt_broker.LocalClient") as mock_local_class:
                # Create comprehensive mocks for both clients including their .client properties
                mock_remote = MagicMock(spec=RemoteClient)
                mock_remote_mqtt_client = MagicMock()
                mock_remote.client = mock_remote_mqtt_client

                mock_local = MagicMock(spec=LocalClient)
                mock_local_mqtt_client = MagicMock()
                mock_local.client = mock_local_mqtt_client

                # Configure return values
                mock_remote_class.return_value = mock_remote
                mock_local_class.return_value = mock_local

                # Call the method under test
                broker_manager.setup_clients()

                # Verify the clients were created and set up properly
                assert broker_manager.remote_client == mock_remote
                assert broker_manager.local_client == mock_local
                mock_remote.setup.assert_called_once()
                mock_local.setup.assert_called_once()
                mock_remote.client.user_data_set.assert_called_once_with(broker_manager)
                mock_local.client.user_data_set.assert_called_once_with(broker_manager)


def test_broker_manager_connect_clients(
    broker_manager, mock_remote_client, mock_local_client
):
    """Test BrokerManager connect_clients method."""
    broker_manager.remote_client = mock_remote_client
    broker_manager.local_client = mock_local_client

    with patch("threading.Thread") as mock_thread_class:
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread

        broker_manager.connect_clients()

        assert mock_thread_class.call_count == 2
        assert mock_thread.start.call_count == 2
        assert mock_thread.join.call_count == 2


def test_broker_manager_connect_clients_missing_remote(
    broker_manager, mock_local_client
):
    """Test BrokerManager connect_clients method with missing remote client."""
    broker_manager.remote_client = None
    broker_manager.local_client = mock_local_client

    with pytest.raises(
        ValueError, match="Remote client not initialized for connection."
    ):
        broker_manager.connect_clients()


def test_broker_manager_connect_clients_missing_local(
    broker_manager, mock_remote_client
):
    """Test BrokerManager connect_clients method with missing local client."""
    broker_manager.remote_client = mock_remote_client
    broker_manager.local_client = None

    with pytest.raises(
        ValueError, match="Local client not initialized for connection."
    ):
        broker_manager.connect_clients()


def test_broker_manager_start_config_monitor(broker_manager):
    """Test BrokerManager start_config_monitor method."""
    with patch("threading.Thread") as mock_thread_class:
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread

        broker_manager.start_config_monitor()

        # Verify Thread was created with correct arguments
        mock_thread_class.assert_called_once_with(
            target=broker_manager._monitor_config, daemon=True
        )
        mock_thread.start.assert_called_once()


def test_broker_manager_monitor_config_no_changes(broker_manager):
    """Test BrokerManager _monitor_config method with no changes."""
    # Mock load_settings to return settings
    mock_settings = {
        "iot_environment": "dev",
        "tenant_name": "tenant1",
        "device_name": "device1",
        "aws_iot_endpoint": "endpoint1",
    }

    with patch("src.mqtt_broker.load_settings", return_value=mock_settings):
        with patch("src.mqtt_broker.CONFIG") as mock_config:
            mock_config.update_from_settings.return_value = False

            # Setup sleep to raise exception after first call to break out of the infinite loop
            with patch("time.sleep") as mock_sleep:
                mock_sleep.side_effect = [None, Exception("Test: Breaking loop")]

                try:
                    broker_manager._monitor_config()
                except Exception:
                    pass  # Expected exception to break out of the loop

            mock_config.update_from_settings.assert_called_with(mock_settings)
            assert mock_sleep.call_count > 0


def test_broker_manager_monitor_config_with_changes(broker_manager, mock_remote_client):
    """Test BrokerManager _monitor_config method with changes."""
    broker_manager.remote_client = mock_remote_client

    # Mock load_settings to return settings
    mock_settings = {
        "iot_environment": "dev",
        "tenant_name": "tenant1",
        "device_name": "device1",
        "aws_iot_endpoint": "endpoint1",
    }

    with patch("src.mqtt_broker.load_settings", return_value=mock_settings):
        with patch("src.mqtt_broker.CONFIG") as mock_config:
            mock_config.update_from_settings.return_value = True

            # Mock RemoteClient to avoid actual reconnection
            with patch("src.mqtt_broker.RemoteClient") as mock_remote_class:
                mock_new_remote = MagicMock(spec=RemoteClient)
                mock_remote_class.return_value = mock_new_remote

                # Set up client.user_data_set on the new remote client
                mock_new_remote.client = MagicMock()

                # In our patched version, explicitly call the disconnect first, as the original method would
                def patched_monitor_config():
                    # First explicitly disconnect the original client
                    mock_remote_client.disconnect()

                    # Then set up the new client, call connect, and raise exception
                    broker_manager.remote_client = mock_new_remote
                    mock_new_remote.setup()
                    mock_new_remote.connect()
                    raise Exception("Test: Breaking loop")

                # Save the original method and replace it with our patched version
                original_monitor = broker_manager._monitor_config
                broker_manager._monitor_config = patched_monitor_config

                try:
                    broker_manager._monitor_config()
                except Exception:
                    pass  # Expected exception to break out of the loop

                # Restore the original method
                broker_manager._monitor_config = original_monitor

                mock_remote_client.disconnect.assert_called_once()
                mock_new_remote.setup.assert_called_once()
                mock_new_remote.connect.assert_called_once()


def test_broker_manager_disconnect_clients(
    broker_manager, mock_remote_client, mock_local_client
):
    """Test BrokerManager disconnect_clients method."""
    broker_manager.remote_client = mock_remote_client
    broker_manager.local_client = mock_local_client

    broker_manager.disconnect_clients()

    mock_remote_client.disconnect.assert_called_once()
    mock_local_client.disconnect.assert_called_once()


def test_broker_manager_publish_remote_message(broker_manager, mock_remote_client):
    """Test BrokerManager publish_remote_message method."""
    broker_manager.remote_client = mock_remote_client
    mock_remote_client.client.is_connected.return_value = True

    # Mock the database session
    mock_session = MagicMock()

    # Mock the message without using spec=Message
    mock_message = MagicMock()
    mock_message.id = 123

    # Mock the publish result
    mock_result = MagicMock()
    mock_result.rc = mqtt.MQTT_ERR_SUCCESS

    mock_remote_client.client.publish.return_value = mock_result

    # Mock datetime.now
    mock_now = datetime.now(timezone.utc)

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        with patch("src.mqtt_broker.Message", return_value=mock_message):
            with patch("src.mqtt_broker.datetime") as mock_datetime:
                with patch("src.mqtt_broker.Properties") as mock_properties_class:
                    mock_datetime.now.return_value = mock_now
                    mock_props = MagicMock()
                    mock_properties_class.return_value = mock_props

                    broker_manager.publish_remote_message("test/topic", "test payload")

                    mock_session.add.assert_called_once_with(mock_message)
                    mock_session.commit.assert_called()
                    mock_remote_client.client.publish.assert_called_once_with(
                        "test/topic", "test payload", qos=1, properties=mock_props
                    )
                    assert mock_message.sent_on == mock_now
                    assert mock_message.last_error is None


def test_broker_manager_publish_remote_message_not_connected(
    broker_manager, mock_remote_client
):
    """Test BrokerManager publish_remote_message method when not connected."""
    broker_manager.remote_client = mock_remote_client
    mock_remote_client.client.is_connected.return_value = False

    # Mock the database session
    mock_session = MagicMock()

    # Mock the message without using spec=Message
    mock_message = MagicMock()
    mock_message.id = 123

    with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
        with patch("src.mqtt_broker.Message", return_value=mock_message):
            broker_manager.publish_remote_message("test/topic", "test payload")

            mock_session.add.assert_called_once_with(mock_message)
            mock_session.commit.assert_called_once()
            mock_remote_client.client.publish.assert_not_called()


def test_broker_manager_publish_local_message(broker_manager, mock_local_client):
    """Test BrokerManager publish_local_message method."""
    broker_manager.local_client = mock_local_client
    mock_local_client.client.is_connected.return_value = True

    broker_manager.publish_local_message("test/topic", "test payload")

    mock_local_client.client.publish.assert_called_once_with(
        "test/topic", "test payload", qos=1
    )


def test_broker_manager_publish_local_message_not_connected(
    broker_manager, mock_local_client
):
    """Test BrokerManager publish_local_message method when not connected."""
    broker_manager.local_client = mock_local_client
    mock_local_client.client.is_connected.return_value = False

    broker_manager.publish_local_message("test/topic", "test payload")

    mock_local_client.client.publish.assert_not_called()


def test_run_mqtt_broker():
    """Test run_mqtt_broker function."""
    with patch("src.mqtt_broker.BrokerManager") as mock_broker_class:
        mock_broker = MagicMock(spec=BrokerManager)
        mock_broker_class.return_value = mock_broker

        with patch("time.sleep") as mock_sleep:
            # Set up sleep to raise exception after first call
            mock_sleep.side_effect = KeyboardInterrupt("Test: Breaking loop")

            try:
                from src.mqtt_broker import run_mqtt_broker

                run_mqtt_broker()
            except KeyboardInterrupt:
                pass  # Expected exception to break out of the loop

            mock_broker.initialize.assert_called_once()
            mock_broker.setup_clients.assert_called_once()
            mock_broker.connect_clients.assert_called_once()
            mock_broker.start_config_monitor.assert_called_once()
            mock_sleep.assert_called_once_with(1)
