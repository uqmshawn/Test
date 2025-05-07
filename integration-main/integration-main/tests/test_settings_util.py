"""Tests for settings_util.py functions."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from sqlalchemy.exc import SQLAlchemyError

from src.settings_util import load_settings, save_settings
from src.models import Settings


@pytest.fixture
def mock_settings():
    """Fixture to provide mock settings."""
    return {
        "iot_environment": "test",
        "tenant_name": "test_tenant",
        "device_name": "test_device",
        "aws_iot_endpoint": "test.endpoint.amazonaws.com",
    }


@pytest.fixture
def mock_db_settings():
    """Fixture to provide mock database settings."""
    settings = MagicMock(spec=Settings)
    settings.iot_environment = "test"
    settings.tenant_name = "test_tenant"
    settings.device_name = "test_device"
    settings.aws_iot_endpoint = "test.endpoint.amazonaws.com"
    return settings


@patch("src.settings_util.SessionLocal")
def test_load_settings_success(mock_session_local, mock_db_settings) -> None:
    """Test successful settings loading."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session
    mock_session.query.return_value.first.return_value = mock_db_settings

    # Act
    result = load_settings()

    # Assert
    assert result == {
        "iot_environment": "test",
        "tenant_name": "test_tenant",
        "device_name": "test_device",
        "aws_iot_endpoint": "test.endpoint.amazonaws.com",
    }
    mock_session.query.assert_called_once()


@patch("src.settings_util.SessionLocal")
def test_load_settings_no_settings(mock_session_local) -> None:
    """Test loading settings when none exist."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session
    mock_session.query.return_value.first.return_value = None

    # Act
    result = load_settings()

    # Assert
    assert not result
    mock_session.query.assert_called_once()


@patch("src.settings_util.SessionLocal")
def test_load_settings_db_error(mock_session_local) -> None:
    """Test loading settings with database error."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session
    mock_session.query.side_effect = SQLAlchemyError("Database error")

    # Act
    result = load_settings()

    # Assert
    assert not result


@patch("src.settings_util.SessionLocal")
def test_save_settings_new(mock_session_local, mock_settings) -> None:
    """Test saving new settings."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session
    mock_session.query.return_value.first.return_value = None

    # Act
    save_settings(mock_settings)

    # Assert
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()


@patch("src.settings_util.SessionLocal")
def test_save_settings_update(
    mock_session_local, mock_settings, mock_db_settings
) -> None:
    """Test updating existing settings."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session
    mock_session.query.return_value.first.return_value = mock_db_settings

    # Act
    save_settings(mock_settings)

    # Assert
    assert mock_db_settings.iot_environment == "test"
    assert mock_db_settings.tenant_name == "test_tenant"
    assert mock_db_settings.device_name == "test_device"
    assert mock_db_settings.aws_iot_endpoint == "test.endpoint.amazonaws.com"
    assert isinstance(mock_db_settings.updated_at, datetime)
    mock_session.commit.assert_called_once()


@patch("src.settings_util.SessionLocal")
def test_save_settings_db_error(mock_session_local, mock_settings) -> None:
    """Test saving settings with database error."""
    # Arrange
    mock_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_session
    mock_session.commit.side_effect = SQLAlchemyError("Database error")

    # Act & Assert
    with pytest.raises(SQLAlchemyError):
        save_settings(mock_settings)
