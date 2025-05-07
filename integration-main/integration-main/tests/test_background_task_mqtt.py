"""Tests for background_task.py MQTT-related functions."""

import pytest
from unittest.mock import MagicMock, patch
import paho.mqtt.client as mqtt
from typing import Optional, Dict, Union
from datetime import datetime, timezone, timedelta
import time
import json

from background_task import (
    on_disconnect,
    init_mqtt_client,
    start_gps_outbound_thread,
    process_gps_outbound,
)


@pytest.fixture(scope="module")
def mock_db_engine():
    """Mock SQLAlchemy engine to prevent actual database connections."""
    with patch("models.create_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        yield mock_engine


@pytest.fixture
def mock_db(mock_db_engine):
    """Mock database session and models."""
    with patch("background_task.SessionLocal") as mock_session_local:
        mock_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_session
        mock_session_local.return_value.__exit__.return_value = None

        # Mock the query builder
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_query.all.return_value = []

        yield mock_session


@pytest.fixture
def mock_mqtt_client():
    """Mock MQTT client."""
    mock_client = MagicMock()
    return mock_client


def test_on_disconnect():
    """Test on_disconnect callback."""
    # Arrange
    client = MagicMock()
    client.reconnect.return_value = 0
    userdata = {}
    disconnect_flags = {}
    reason_code = mqtt.MQTT_ERR_SUCCESS
    properties = None

    # Act
    on_disconnect(client, userdata, disconnect_flags, reason_code, properties)

    # Assert
    client.reconnect.assert_called_once()


def test_on_disconnect_retry():
    """Test on_disconnect callback with retry."""
    # Arrange
    client = MagicMock()
    client.reconnect.side_effect = [1, 1, 0]  # Fail twice, succeed on third try
    userdata = {}
    disconnect_flags = {}
    reason_code = mqtt.MQTT_ERR_CONN_LOST
    properties = None

    # Act
    with patch("src.background_task.time.sleep") as mock_sleep:
        on_disconnect(client, userdata, disconnect_flags, reason_code, properties)

    # Assert
    assert client.reconnect.call_count == 3
    assert mock_sleep.call_count == 2  # Should sleep between retries
    mock_sleep.assert_called_with(5)  # Default retry delay is 5 seconds


def test_on_disconnect_all_retries_fail():
    """Test on_disconnect callback when all retries fail."""
    # Arrange
    client = MagicMock()
    client.reconnect.return_value = 1  # Always fail
    userdata = {}
    disconnect_flags = {}
    reason_code = mqtt.MQTT_ERR_CONN_LOST
    properties = None

    # Act
    with patch("src.background_task.time.sleep") as mock_sleep:
        on_disconnect(client, userdata, disconnect_flags, reason_code, properties)

    # Assert
    assert client.reconnect.call_count == 3  # Default max retries is 3
    assert mock_sleep.call_count == 3  # Sleeps after each failed attempt
    mock_sleep.assert_called_with(5)  # Default retry delay is 5 seconds


def test_init_mqtt_client():
    """Test MQTT client initialization."""
    # Arrange
    broker_address = "test.mosquitto.org"
    port = 1883
    client_id = "test_client"
    mock_client = MagicMock()
    mock_client.on_disconnect = MagicMock()  # Add on_disconnect attribute
    mock_client.connect = MagicMock(return_value=0)  # Make connect return success

    # Act
    with patch(
        "paho.mqtt.client.Client", return_value=mock_client
    ) as mock_client_class:
        # Also patch uuid to return a predictable value
        with patch(
            "src.background_task.uuid.uuid4",
            return_value="12345678-1234-5678-1234-567812345678",
        ):
            client = init_mqtt_client(broker_address, port, client_id)

            # Assert
            mock_client_class.assert_called_once()
            call_args = mock_client_class.call_args[1]
            assert client_id in call_args["client_id"]
            assert call_args["protocol"] == mqtt.MQTTv5
            assert hasattr(client, "on_disconnect")
            # We now use keepalive=60 in the connect call
            mock_client.connect.assert_called_once_with(
                broker_address, port, keepalive=60, clean_start=True
            )


def test_init_mqtt_client_failure():
    """Test MQTT client initialization failure."""
    # Arrange
    broker_address = "test.mosquitto.org"
    port = 1883
    client_id = "test_client"

    # Create a mock client
    mock_client = MagicMock(spec=mqtt.Client)

    # Mock both the Client constructor and connect_mqtt_client
    with patch("paho.mqtt.client.Client", return_value=mock_client):
        with patch("src.background_task.connect_mqtt_client", return_value=False):
            # Act
            result = init_mqtt_client(broker_address, port, client_id)

            # Assert
            assert result is None


def test_start_gps_outbound_thread():
    """Test starting GPS outbound thread."""
    # Arrange
    mock_client = MagicMock()

    # Act
    thread = start_gps_outbound_thread(mock_client)

    # Assert
    assert thread.is_alive()
    assert thread.daemon


@patch("paho.mqtt.client.Client")
def test_process_gps_outbound(mock_mqtt_client_class, mock_db):
    """Test processing GPS outbound data."""
    # Arrange
    mock_client = MagicMock()
    mock_mqtt_client_class.return_value = mock_client

    # Set up mock outbound data and GPS records
    mock_outbound = MagicMock()
    mock_outbound.last_sent = (
        datetime.now(timezone.utc) - timedelta(minutes=30)
    ).isoformat()
    mock_gps_records = [
        MagicMock(
            timestamp=(datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat(),
            latitude=1.0,
            longitude=2.0,
            speed=30.0,
            heading=90.0,
            altitude=100.0,
            satellites=8,
            hdop=1.0,
            pdop=2.0,
            location_timestamp=(
                datetime.now(timezone.utc) - timedelta(minutes=25)
            ).isoformat(),
        ),
        MagicMock(
            timestamp=(datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),
            latitude=1.1,  # Different location
            longitude=2.1,
            speed=35.0,
            heading=95.0,
            altitude=105.0,
            satellites=8,
            hdop=1.0,
            pdop=2.1,
            location_timestamp=(
                datetime.now(timezone.utc) - timedelta(minutes=20)
            ).isoformat(),
        ),
    ]

    # Set up mock query results
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = mock_outbound
    mock_query.all.return_value = mock_gps_records

    # Act
    process_gps_outbound(mock_client)

    # Assert
    mock_client.publish.assert_called_once()
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@patch("paho.mqtt.client.Client")
def test_process_gps_outbound_no_data(mock_mqtt_client_class, mock_db):
    """Test processing GPS outbound data with no data."""
    # Arrange
    mock_client = MagicMock()
    mock_mqtt_client_class.return_value = mock_client

    # Set up mock query results
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = None
    mock_query.all.return_value = []

    # Act
    process_gps_outbound(mock_client)

    # Assert
    mock_client.publish.assert_not_called()
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()
