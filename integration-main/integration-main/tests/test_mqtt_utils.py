"""Tests for mqtt_utils.py functions."""

import pytest
from unittest.mock import MagicMock, patch
import paho.mqtt.client as mqtt
from src.mqtt_utils import connect_mqtt_client


def test_connect_mqtt_client_success() -> None:
    """Test successful MQTT client connection."""
    # Arrange
    client = MagicMock(spec=mqtt.Client)
    broker_address = "localhost"
    port = 1883
    client.connect.return_value = mqtt.MQTT_ERR_SUCCESS
    client.is_connected.return_value = True

    # Act
    with patch("time.sleep") as mock_sleep:  # Mock sleep to speed up test
        result = connect_mqtt_client(client, broker_address, port)

    # Assert
    assert result is True
    # We now use keepalive=15 for localhost connections
    client.connect.assert_called_once_with(
        broker_address, port, keepalive=15, clean_start=True
    )
    client.loop_start.assert_called_once()
    # We now have a delay after successful connection to check stability
    mock_sleep.assert_called_once_with(0.5)


def test_connect_mqtt_client_retry() -> None:
    """Test MQTT client connection with retry."""
    # Arrange
    client = MagicMock(spec=mqtt.Client)
    broker_address = "localhost"
    port = 1883
    client.is_connected.return_value = True

    # First call fails, second succeeds
    client.connect.side_effect = [mqtt.MQTT_ERR_CONN_REFUSED, mqtt.MQTT_ERR_SUCCESS]

    # Act
    with patch("time.sleep") as mock_sleep:  # Mock sleep to speed up test
        result = connect_mqtt_client(client, broker_address, port)

    # Assert
    assert result is True
    assert client.connect.call_count == 2
    # We now have multiple sleep calls - one for retry delay and one for connection stability check
    assert mock_sleep.call_count == 2
    # Check that the first call is the retry delay
    assert mock_sleep.call_args_list[0][0][0] == 5
    # Check that the second call is the stability check
    assert mock_sleep.call_args_list[1][0][0] == 0.5
    client.loop_start.assert_called_once()


def test_connect_mqtt_client_multiple_retries() -> None:
    """Test MQTT client connection with multiple retries."""
    # Arrange
    client = MagicMock(spec=mqtt.Client)
    broker_address = "localhost"
    port = 1883
    client.is_connected.return_value = True

    # First two calls fail, third succeeds
    client.connect.side_effect = [
        mqtt.MQTT_ERR_CONN_REFUSED,
        mqtt.MQTT_ERR_CONN_REFUSED,
        mqtt.MQTT_ERR_SUCCESS,
    ]

    # Act
    with patch("time.sleep") as mock_sleep:  # Mock sleep to speed up test
        result = connect_mqtt_client(client, broker_address, port)

    # Assert
    assert result is True
    assert client.connect.call_count == 3
    # We now have 3 sleep calls - two for retry delays and one for connection stability check
    assert mock_sleep.call_count == 3
    # First two calls are for retry delays, last one is for stability check
    assert mock_sleep.call_args_list[0][0][0] == 5  # First retry
    assert mock_sleep.call_args_list[1][0][0] > 5  # Second retry with backoff
    # Last call is for stability check (approximately 0.5)
    assert 0.4 < mock_sleep.call_args_list[2][0][0] < 0.6
    client.loop_start.assert_called_once()
