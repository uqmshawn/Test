"""Tests for secrets_util.py functions."""

import pytest
from unittest.mock import mock_open, patch
import toml
from src.secrets_util import load_secrets


def test_load_secrets_success() -> None:
    """Test successful secrets loading."""
    # Arrange
    secrets_path = "/app/.secrets/secrets.toml"
    mock_secrets = {
        "router_ip": "192.168.1.1",
        "router_userid": "admin",
        "router_password": "pw",
    }
    mock_content = toml.dumps(mock_secrets)

    # Act
    with patch("builtins.open", mock_open(read_data=mock_content)):
        result = load_secrets(secrets_path)

    # Assert
    assert result == mock_secrets


def test_load_secrets_file_not_found() -> None:
    """Test secrets loading when file is not found."""
    # Arrange
    secrets_path = "/app/.secrets/secrets.toml"

    # Act
    with patch("builtins.open", mock_open()) as mock_file:
        mock_file.side_effect = FileNotFoundError()
        result = load_secrets(secrets_path)

    # Assert
    assert not result


def test_load_secrets_invalid_toml() -> None:
    """Test secrets loading with invalid TOML content."""
    # Arrange
    secrets_path = "/app/.secrets/secrets.toml"
    invalid_content = "invalid toml content"

    # Act
    with patch("builtins.open", mock_open(read_data=invalid_content)):
        result = load_secrets(secrets_path)

    # Assert
    assert not result


def test_load_secrets_custom_path() -> None:
    """Test secrets loading with custom path."""
    # Arrange
    custom_path = "/custom/path/secrets.toml"
    mock_secrets = {
        "router_ip": "192.168.1.1",
        "router_userid": "admin",
        "router_password": "pw",
    }
    mock_content = toml.dumps(mock_secrets)

    # Act
    with patch("builtins.open", mock_open(read_data=mock_content)):
        result = load_secrets(custom_path)

    # Assert
    assert result == mock_secrets
