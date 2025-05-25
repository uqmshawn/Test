"""Tests for hash_password.py functions."""

import pytest
from unittest.mock import patch
import bcrypt
from src.hash_password import hash_password


def test_hash_password() -> None:
    """Test password hashing."""
    # Arrange
    plain_password = "test_password"

    # Act
    hashed = hash_password(plain_password)

    # Assert
    assert isinstance(hashed, str)
    assert hashed.startswith("$2b$")  # bcrypt hash format
    assert len(hashed) > 0


def test_hash_password_empty() -> None:
    """Test hashing an empty password."""
    # Arrange
    plain_password = ""

    # Act
    hashed = hash_password(plain_password)

    # Assert
    assert isinstance(hashed, str)
    assert hashed.startswith("$2b$")
    assert len(hashed) > 0


def test_hash_password_special_chars() -> None:
    """Test hashing a password with special characters."""
    # Arrange
    plain_password = "test!@#$%^&*()_+"

    # Act
    hashed = hash_password(plain_password)

    # Assert
    assert isinstance(hashed, str)
    assert hashed.startswith("$2b$")
    assert len(hashed) > 0


@patch("bcrypt.gensalt")
def test_hash_password_mock_salt(mock_gensalt) -> None:
    """Test password hashing with mocked salt."""
    # Arrange
    plain_password = "test_password"
    mock_salt = (
        b"$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj"  # Example bcrypt salt
    )
    mock_gensalt.return_value = mock_salt

    # Act
    hashed = hash_password(plain_password)

    # Assert
    assert isinstance(hashed, str)
    assert hashed.startswith("$2b$")
    mock_gensalt.assert_called_once()
