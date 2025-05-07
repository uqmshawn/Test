"""Common pytest fixtures for the integration project."""

import pytest
from typing import Generator
import requests
from unittest.mock import MagicMock, patch
from sqlalchemy.exc import SQLAlchemyError
import os
import logging
from logging.handlers import RotatingFileHandler


@pytest.fixture
def mock_requests_session() -> Generator[MagicMock, None, None]:
    """Creates a mock requests.Session object."""
    session = MagicMock(spec=requests.Session)
    yield session


@pytest.fixture
def mock_mqtt_client() -> Generator[MagicMock, None, None]:
    """Creates a mock MQTT client."""
    client = MagicMock()
    # Add common MQTT client attributes
    client.is_connected.return_value = True
    client.loop_start = MagicMock()
    client.loop_stop = MagicMock()
    client.connect = MagicMock()
    client.disconnect = MagicMock()
    client.publish = MagicMock()
    client.subscribe = MagicMock()
    yield client


@pytest.fixture
def sample_gps_data() -> dict:
    """Returns sample GPS data for testing."""
    return {
        "stat": "ok",
        "response": {
            "location": {
                "latitude": 10.0,
                "longitude": 20.0,
                "altitude": 30.0,
                "speed": 5.0,
                "heading": 90.0,
                "pdop": 1.0,
                "hdop": 0.8,
                "vdop": 0.6,
                "timestamp": 1678886400,
            }
        },
    }


@pytest.fixture
def mock_settings() -> dict:
    """Returns common settings for testing."""
    return {
        "iot_environment": "test",
        "tenant_name": "test_tenant",
        "device_name": "test_device",
        "aws_iot_endpoint": "test.endpoint.amazonaws.com",
    }


@pytest.fixture
def mock_db_settings() -> MagicMock:
    """Returns mock database settings."""
    settings = MagicMock()
    settings.iot_environment = "test"
    settings.tenant_name = "test_tenant"
    settings.device_name = "test_device"
    settings.aws_iot_endpoint = "test.endpoint.amazonaws.com"
    return settings


@pytest.fixture(scope="module")
def mock_db_engine() -> Generator[MagicMock, None, None]:
    """Mock SQLAlchemy engine to prevent actual database connections."""
    with patch("models.create_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        yield mock_engine


@pytest.fixture
def mock_db(mock_db_engine) -> Generator[MagicMock, None, None]:
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
def mock_logger() -> Generator[MagicMock, None, None]:
    """Mock logger for testing."""
    with patch(
        "src.logger_setup.logging.getLogger", return_value=MagicMock()
    ) as mock_get_logger:
        logger = mock_get_logger.return_value
        logger.handlers = []
        # Mock removeHandler and addHandler methods
        logger.removeHandler = MagicMock()
        logger.addHandler = MagicMock()
        yield logger


@pytest.fixture
def mock_makedirs() -> Generator[MagicMock, None, None]:
    """Mock os.makedirs for testing."""
    with patch("src.logger_setup.os.makedirs") as mock:
        yield mock


@pytest.fixture
def mock_path_join() -> Generator[MagicMock, None, None]:
    """Mock os.path.join for testing."""
    with patch(
        "src.logger_setup.os.path.join", return_value="/test/path/test.log"
    ) as mock:
        yield mock


@pytest.fixture
def mock_rotating_file_handler() -> Generator[MagicMock, None, None]:
    """Mock RotatingFileHandler for testing."""
    with patch("src.logger_setup.RotatingFileHandler") as mock_handler_class:
        mock_instance = MagicMock()
        mock_instance.baseFilename = "/test/path/test.log"
        mock_handler_class.return_value = mock_instance
        yield mock_handler_class
