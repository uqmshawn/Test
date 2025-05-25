"""Tests for the MQTT client classes in mqtt_broker.py."""

import pytest
from unittest.mock import MagicMock, patch, ANY
import paho.mqtt.client as mqtt
import threading
import time
import os
import sys
from datetime import datetime, timezone
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes

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
    MQTTClient,
    RemoteClient,
    LocalClient,
    Configuration,
    CertificateManager,
    attempt_reconnect,
    process_single_message,
    process_batch_messages,
    on_remote_disconnect,
    on_local_disconnect,
    remote_on_message,
    on_connect,
    on_local_message,
    aws_on_log,
)


@pytest.fixture
def mock_mqtt_client():
    """Create a mock MQTT client with all required methods."""
    client = MagicMock(spec=mqtt.Client)
    client.is_connected.return_value = False
    client.loop_stop = MagicMock()
    client.disconnect = MagicMock()
    client.enable_logger = MagicMock()
    client.reconnect_delay_set = MagicMock()
    client.subscribe = MagicMock()
    client.publish = MagicMock()
    client.reconnect = MagicMock()
    client.loop_start = MagicMock()
    client.connect = MagicMock()
    return client


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


def test_mqtt_client_init():
    """Test MQTTClient initialization."""
    with patch("src.mqtt_broker.mqtt.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Also patch uuid to return a predictable value
        with patch(
            "src.mqtt_broker.uuid.uuid4",
            return_value="12345678-1234-5678-1234-567812345678",
        ):
            client = MQTTClient("test_client")

            # Verify the client was created with a client_id that contains the base ID
            mock_client_class.assert_called_once()
            call_args = mock_client_class.call_args[1]
            assert "test_client" in call_args["client_id"]
            assert call_args["protocol"] == mqtt.MQTTv5
            assert client.client == mock_client
            assert client.is_remote is False

            # Test with is_remote=True
            client = MQTTClient("test_client", is_remote=True)
            assert client.is_remote is True


def test_mqtt_client_disconnect():
    """Test MQTTClient disconnect method."""
    with patch("src.mqtt_broker.mqtt.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.loop_stop = MagicMock()
        mock_client.disconnect = MagicMock()
        mock_client.is_connected.return_value = True
        # Set the _message_processor_running attribute to simulate a running processor
        mock_client._message_processor_running = True
        mock_client_class.return_value = mock_client

        client = MQTTClient("test_client")
        client.disconnect()

        # Verify all callbacks are cleared
        mock_client.loop_stop.assert_called_once()
        assert mock_client.on_disconnect is None
        assert mock_client.on_connect is None
        assert mock_client.on_message is None
        assert mock_client.on_publish is None
        assert mock_client.on_subscribe is None
        assert mock_client.on_unsubscribe is None

        # Verify message processor flag is reset
        assert mock_client._message_processor_running is False

        # Verify disconnect is called since is_connected returns True
        mock_client.disconnect.assert_called_once()


def test_mqtt_client_disconnect_error():
    """Test MQTTClient disconnect method with error."""
    with patch("src.mqtt_broker.mqtt.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.loop_stop = MagicMock()
        mock_client.disconnect = MagicMock(side_effect=Exception("Test error"))
        mock_client.is_connected.return_value = True
        # Set the _message_processor_running attribute to simulate a running processor
        mock_client._message_processor_running = True
        mock_client_class.return_value = mock_client

        client = MQTTClient("test_client")
        client.disconnect()

        # Verify callbacks are still cleared even when disconnect fails
        mock_client.loop_stop.assert_called_once()
        assert mock_client.on_disconnect is None
        assert mock_client.on_connect is None
        assert mock_client.on_message is None
        assert mock_client.on_publish is None
        assert mock_client.on_subscribe is None
        assert mock_client.on_unsubscribe is None

        # Verify message processor flag is reset
        assert mock_client._message_processor_running is False

        # Verify disconnect is called but fails with exception
        mock_client.disconnect.assert_called_once()


def test_remote_client_init(mock_config, mock_cert_manager):
    """Test RemoteClient initialization."""
    with patch("src.mqtt_broker.mqtt.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Also patch uuid to return a predictable value
        with patch(
            "src.mqtt_broker.uuid.uuid4",
            return_value="12345678-1234-5678-1234-567812345678",
        ):
            client = RemoteClient(mock_config, mock_cert_manager)

            # Verify the client was created with a client_id that contains the expected base ID
            expected_base_client_id = (
                f"{mock_config.tenant_name}_{mock_config.device_name}_mqtt_broker"
            )
            mock_client_class.assert_called_once()
            call_args = mock_client_class.call_args[1]
            assert expected_base_client_id in call_args["client_id"]
            assert call_args["protocol"] == mqtt.MQTTv5
            assert client.client == mock_client
            assert client.is_remote is True
            assert client.config == mock_config
            assert client.cert_manager == mock_cert_manager


def test_remote_client_setup(mock_config, mock_cert_manager):
    """Test RemoteClient setup method."""
    with patch("src.mqtt_broker.mqtt.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.enable_logger = MagicMock()
        mock_client_class.return_value = mock_client

        client = RemoteClient(mock_config, mock_cert_manager)
        client.setup()

        mock_cert_manager.configure_client.assert_called_once_with(mock_client)
        mock_client.on_disconnect = on_remote_disconnect
        mock_client.on_log = aws_on_log
        mock_client.enable_logger.assert_called_once()
        mock_client.on_message = remote_on_message
        mock_client.on_connect = on_connect


def test_remote_client_connect(mock_config, mock_cert_manager):
    """Test RemoteClient connect method with message processor not running."""
    with patch("src.mqtt_broker.mqtt.Client") as mock_client_class:
        mock_client = MagicMock()
        # Set the _message_processor_running attribute to False to simulate a fresh client
        mock_client._message_processor_running = False
        mock_client_class.return_value = mock_client

        with patch("src.mqtt_broker.connect_mqtt_client") as mock_connect:
            with patch("threading.Thread") as mock_thread:
                client = RemoteClient(mock_config, mock_cert_manager)
                client.connect()

                mock_connect.assert_called_once_with(
                    mock_client, mock_config.aws_iot_endpoint, 8883
                )
                # Thread should be created since _message_processor_running is False
                mock_thread.assert_called_once()


def test_remote_client_connect_processor_running(mock_config, mock_cert_manager):
    """Test RemoteClient connect method with message processor already running."""
    with patch("src.mqtt_broker.mqtt.Client") as mock_client_class:
        mock_client = MagicMock()
        # Set the _message_processor_running attribute to True to simulate a client with processor already running
        mock_client._message_processor_running = True
        mock_client_class.return_value = mock_client

        with patch("src.mqtt_broker.connect_mqtt_client") as mock_connect:
            with patch("threading.Thread") as mock_thread:
                client = RemoteClient(mock_config, mock_cert_manager)
                client.connect()

                mock_connect.assert_called_once_with(
                    mock_client, mock_config.aws_iot_endpoint, 8883
                )
                # Thread should NOT be created since _message_processor_running is True
                mock_thread.assert_not_called()


def test_local_client_init():
    """Test LocalClient initialization."""
    with patch("src.mqtt_broker.mqtt.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Also patch uuid to return a predictable value
        with patch(
            "src.mqtt_broker.uuid.uuid4",
            return_value="12345678-1234-5678-1234-567812345678",
        ):
            client = LocalClient()

            # Verify the client was created with a client_id that contains the base ID
            mock_client_class.assert_called_once()
            call_args = mock_client_class.call_args[1]
            assert "local_broker" in call_args["client_id"]
            assert call_args["protocol"] == mqtt.MQTTv5
            assert client.client == mock_client
            assert client.is_remote is False


def test_local_client_setup():
    """Test LocalClient setup method."""
    with patch("src.mqtt_broker.mqtt.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.reconnect_delay_set = MagicMock()
        mock_client_class.return_value = mock_client

        client = LocalClient()
        client.setup()

        mock_client.on_disconnect = on_local_disconnect
        mock_client.reconnect_delay_set.assert_called_once_with(
            min_delay=1, max_delay=30
        )
        mock_client.on_message = on_local_message  # LocalClient uses on_local_message


def test_local_client_connect():
    """Test LocalClient connect method."""
    with patch("src.mqtt_broker.mqtt.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.subscribe = MagicMock()
        mock_client_class.return_value = mock_client

        with patch("src.mqtt_broker.connect_mqtt_client") as mock_connect:
            with patch.dict(os.environ, {"MQTT_BROKER_ADDRESS": "test_broker"}):
                client = LocalClient()
                client.connect()

                mock_connect.assert_called_once_with(mock_client, "test_broker", 1883)
                mock_client.subscribe.assert_called_once_with("out/#")


def test_attempt_reconnect_success(mock_mqtt_client):
    """Test attempt_reconnect with successful reconnection."""
    mock_mqtt_client.is_connected.return_value = False
    mock_mqtt_client.reconnect.return_value = mqtt.MQTT_ERR_SUCCESS

    result = attempt_reconnect(mock_mqtt_client)

    assert result is True
    mock_mqtt_client.reconnect.assert_called_once()
    mock_mqtt_client.loop_start.assert_not_called()


def test_attempt_reconnect_failure_then_success(mock_mqtt_client):
    """Test attempt_reconnect with initial failure then success."""
    mock_mqtt_client.is_connected.return_value = False
    # Set up side effect for reconnect to always fail with exception
    mock_mqtt_client.reconnect.side_effect = Exception("Test error")
    # Set connect to succeed
    mock_mqtt_client.connect.return_value = mqtt.MQTT_ERR_SUCCESS

    # Set host and port attributes on the mock client
    mock_mqtt_client._host = "test_host"
    mock_mqtt_client._port = 8883

    with patch("src.mqtt_broker.CONFIG") as mock_config:
        mock_config.aws_iot_endpoint = "test_endpoint"

        # Mock time.sleep to prevent actual waiting during the test
        with patch("time.sleep") as mock_sleep:
            # First attempt fails with exception, then tries full reconnect
            result = attempt_reconnect(mock_mqtt_client)

            assert result is True  # Full reconnect succeeds
            # Verify reconnect was called the expected number of times (once per retry)
            assert mock_mqtt_client.reconnect.call_count == 3
            mock_mqtt_client.loop_stop.assert_called_once()
            mock_mqtt_client.disconnect.assert_called_once()
            mock_mqtt_client.connect.assert_called_once_with(
                "test_host", 8883, keepalive=60, clean_start=True
            )
            mock_mqtt_client.loop_start.assert_called_once()
            # Verify sleep was called for backoff delays
            assert mock_sleep.call_count >= 1


def test_attempt_reconnect_all_failures(mock_mqtt_client):
    """Test attempt_reconnect with all failures."""
    mock_mqtt_client.is_connected.return_value = False
    mock_mqtt_client.reconnect.side_effect = Exception("Test error")

    with patch("src.mqtt_broker.CONFIG") as mock_config:
        mock_config.aws_iot_endpoint = "test_endpoint"
        mock_mqtt_client._host = "test_host"
        mock_mqtt_client._port = 8883
        mock_mqtt_client.connect.return_value = mqtt.MQTT_ERR_CONN_REFUSED

        # Mock time.sleep to prevent actual waiting during the test
        with patch("time.sleep") as mock_sleep:
            result = attempt_reconnect(mock_mqtt_client)

            assert result is False
            # Update to match implementation - reconnect is now called 3 times (once per retry)
            assert mock_mqtt_client.reconnect.call_count == 3
            # The loop_stop is called multiple times during the reconnection attempts
            assert mock_mqtt_client.loop_stop.call_count == 3
            mock_mqtt_client.disconnect.assert_called()
            mock_mqtt_client.connect.assert_called_with(
                "test_host", 8883, keepalive=60, clean_start=True
            )
            mock_mqtt_client.loop_start.assert_not_called()
            # Verify sleep was called at least once
            assert mock_sleep.call_count >= 1


def test_process_single_message(mock_mqtt_client):
    """Test process_single_message."""
    # Create a mock message
    mock_message = MagicMock()
    mock_message.id = 123
    mock_message.topic = "test/topic"
    mock_message.payload = "test payload"

    # Mock the publish result
    mock_result = MagicMock()
    mock_result.rc = mqtt.MQTT_ERR_SUCCESS
    mock_mqtt_client.publish.return_value = mock_result

    # Mock datetime.now
    mock_now = datetime.now(timezone.utc)

    with patch("src.mqtt_broker.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_now

        process_single_message(mock_mqtt_client, mock_message, None)

        # Verify the publish call with ANY for properties since it's a complex object
        mock_mqtt_client.publish.assert_called_once()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][0] == "test/topic"
        assert call_args[0][1] == "test payload"
        assert call_args[1]["qos"] == 1
        assert isinstance(call_args[1]["properties"], Properties)
        assert mock_message.sent_on == mock_now
        assert mock_message.last_error is None


def test_process_single_message_failure(mock_mqtt_client):
    """Test process_single_message with publish failure."""
    # Create a mock message
    mock_message = MagicMock()
    mock_message.id = 123
    mock_message.topic = "test/topic"
    mock_message.payload = "test payload"
    mock_message.sent_on = None  # Initialize sent_on as None

    # Mock the publish result with failure
    mock_result = MagicMock()
    mock_result.rc = mqtt.MQTT_ERR_NO_CONN
    mock_mqtt_client.publish.return_value = mock_result

    process_single_message(mock_mqtt_client, mock_message, None)

    # Verify the publish call with ANY for properties since it's a complex object
    mock_mqtt_client.publish.assert_called_once()
    call_args = mock_mqtt_client.publish.call_args
    assert call_args[0][0] == "test/topic"
    assert call_args[0][1] == "test payload"
    assert call_args[1]["qos"] == 1
    assert isinstance(call_args[1]["properties"], Properties)
    assert mock_message.sent_on is None  # sent_on should remain None on failure
    assert mock_message.last_error == "Publish failed with code 4"


def test_process_batch_messages(mock_mqtt_client):
    """Test process_batch_messages."""
    # Create mock messages
    mock_message1 = MagicMock()
    mock_message1.id = 123
    mock_message1.topic = "test/topic1"
    mock_message1.payload = "test payload1"

    mock_message2 = MagicMock()
    mock_message2.id = 456
    mock_message2.topic = "test/topic2"
    mock_message2.payload = "test payload2"

    # Mock the database session
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.all.return_value = [
        mock_message1,
        mock_message2,
    ]

    # Mock process_single_message
    with patch("src.mqtt_broker.process_single_message") as mock_process:
        with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
            process_batch_messages(mock_mqtt_client)

            assert mock_process.call_count == 2
            mock_session.commit.assert_called_once()


def test_process_batch_messages_empty(mock_mqtt_client):
    """Test process_batch_messages with no messages."""
    # Mock the database session with no messages
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.all.return_value = []

    # Mock process_single_message
    with patch("src.mqtt_broker.process_single_message") as mock_process:
        with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
            process_batch_messages(mock_mqtt_client)

            mock_process.assert_not_called()
            mock_session.commit.assert_not_called()


def test_process_batch_messages_error(mock_mqtt_client):
    """Test process_batch_messages with error."""
    # Mock the database session to raise an exception
    mock_session = MagicMock()
    mock_session.query.side_effect = Exception("Test error")

    # Mock process_single_message
    with patch("src.mqtt_broker.process_single_message") as mock_process:
        with patch("src.mqtt_broker.SessionLocal", return_value=mock_session):
            process_batch_messages(mock_mqtt_client)

            mock_process.assert_not_called()
            mock_session.rollback.assert_called_once()


def test_on_remote_disconnect(mock_mqtt_client):
    """Test on_remote_disconnect with immediate success."""
    # Mock the reconnect result
    mock_mqtt_client.reconnect.return_value = mqtt.MQTT_ERR_SUCCESS

    # Use threading to allow us to test infinite retry functions
    def run_with_timeout():
        on_remote_disconnect(mock_mqtt_client, None, 0, 0)

    # Start the function in a thread
    import threading

    thread = threading.Thread(target=run_with_timeout)
    thread.daemon = True
    thread.start()

    # Give it a little time to execute the first attempt
    time.sleep(0.1)

    # Check the results
    mock_mqtt_client.reconnect.assert_called_once()
    # Function should exit on successful reconnect


def test_on_remote_disconnect_with_retries(mock_mqtt_client):
    """Test on_remote_disconnect with retries."""
    # Mock the reconnect result to fail twice then succeed
    mock_mqtt_client.reconnect.side_effect = [
        mqtt.MQTT_ERR_CONN_REFUSED,
        mqtt.MQTT_ERR_CONN_REFUSED,
        mqtt.MQTT_ERR_SUCCESS,
    ]

    # Use threading to allow testing of infinite retry loops
    def run_with_timeout():
        with patch("time.sleep") as mock_sleep:
            on_remote_disconnect(mock_mqtt_client, None, 0, 0)
            return mock_sleep.call_count

    # Start the function in a thread
    import threading
    import queue

    result_queue = queue.Queue()
    thread = threading.Thread(target=lambda: result_queue.put(run_with_timeout()))
    thread.daemon = True
    thread.start()

    # Wait for the function to complete (with timeout)
    thread.join(timeout=1.0)

    # Check the results
    assert (
        mock_mqtt_client.reconnect.call_count == 3
    ), "Should make exactly 3 reconnect attempts"
    # Function should exit after successful reconnection


def test_on_local_disconnect(mock_mqtt_client):
    """Test on_local_disconnect with immediate success."""
    # Mock the reconnect result
    mock_mqtt_client.reconnect.return_value = mqtt.MQTT_ERR_SUCCESS

    # Use threading to allow us to test infinite retry functions
    def run_with_timeout():
        on_local_disconnect(mock_mqtt_client, None, 0, 0)

    # Start the function in a thread
    import threading

    thread = threading.Thread(target=run_with_timeout)
    thread.daemon = True
    thread.start()

    # Give it a little time to execute the first attempt
    time.sleep(0.1)

    # Check the results
    mock_mqtt_client.reconnect.assert_called_once()
    # Function should exit on successful reconnect


def test_remote_on_message():
    """Test remote_on_message."""
    # Create a mock message
    mock_message = MagicMock()
    mock_message.topic = "test/in/topic"
    mock_message.payload = b"test payload"

    # Create a mock userdata with publish_local_message method
    mock_userdata = MagicMock()

    # Create a mock client
    mock_client = MagicMock(spec=mqtt.Client)

    remote_on_message(mock_client, mock_userdata, mock_message)

    mock_userdata.publish_local_message.assert_called_once_with(
        "in/topic", "test payload"
    )


def test_remote_on_message_invalid_topic():
    """Test remote_on_message with invalid topic."""
    # Create a mock message with invalid topic
    mock_message = MagicMock()
    mock_message.topic = "test/topic"  # No "/in/" in topic
    mock_message.payload = b"test payload"

    # Create a mock userdata with publish_local_message method
    mock_userdata = MagicMock()

    # Create a mock client
    mock_client = MagicMock(spec=mqtt.Client)

    remote_on_message(mock_client, mock_userdata, mock_message)

    mock_userdata.publish_local_message.assert_not_called()


def test_on_connect(mock_mqtt_client, mock_config):
    """Test on_connect."""
    # Create a mock userdata with publish_remote_message method
    mock_userdata = MagicMock()

    # Create mock properties
    mock_properties = Properties(PacketTypes.CONNECT)

    # Set up the mock client to return success for subscribe
    mock_mqtt_client.subscribe.return_value = (mqtt.MQTT_ERR_SUCCESS, None)

    # Make sure is_connected returns True to pass the check in on_connect
    mock_mqtt_client.is_connected.return_value = True

    with patch("src.mqtt_broker.CONFIG", mock_config):
        # Mock time.sleep to avoid delays in the test
        with patch("time.sleep"):
            on_connect(mock_mqtt_client, mock_userdata, {}, 0, mock_properties)

            mock_mqtt_client.subscribe.assert_called_once_with(
                f"{mock_config.iot_env}/{mock_config.tenant_name}/{mock_config.device_name}/in/#"
            )
            mock_userdata.publish_remote_message.assert_called_once_with(
                f"{mock_config.iot_env}/{mock_config.tenant_name}/{mock_config.device_name}/out/status",
                '{"message": "MQTT Broker connected via MQTT v5."}',
            )
