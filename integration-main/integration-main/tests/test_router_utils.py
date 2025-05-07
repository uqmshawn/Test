"""Tests for router_utils.py functions."""

import pytest
from unittest.mock import MagicMock, patch
import requests
from src.router_utils import router_login, re_authenticate


def test_router_login_success() -> None:
    """Test successful router login."""
    # Arrange
    router_ip = "192.168.1.1"
    router_userid = "admin"
    router_password = "pw"

    mock_response = MagicMock(spec=requests.Response)
    mock_response.json.return_value = {"stat": "ok"}
    mock_response.text = '{"stat": "ok"}'

    with patch("src.router_utils.requests.Session") as mock_session_class:
        mock_session = mock_session_class.return_value
        mock_session.post.return_value = mock_response

        # Act
        session = router_login(router_ip, router_userid, router_password)

        # Assert
        assert session == mock_session
        mock_session.post.assert_called_once_with(
            f"https://{router_ip}/api/login",
            json={"username": router_userid, "password": router_password},
            verify=False,
        )


def test_router_login_failure() -> None:
    """Test router login failure."""
    # Arrange
    router_ip = "192.168.1.1"
    router_userid = "admin"
    router_password = "pw"

    mock_response = MagicMock(spec=requests.Response)
    mock_response.json.return_value = {"stat": "error"}
    mock_response.text = '{"stat": "error"}'

    with patch("src.router_utils.requests.Session") as mock_session_class:
        mock_session = mock_session_class.return_value
        mock_session.post.return_value = mock_response

        # Act & Assert
        with pytest.raises(RuntimeError, match="Router login failed"):
            router_login(router_ip, router_userid, router_password)


@patch("src.router_utils.router_login")
def test_re_authenticate_success(mock_router_login: MagicMock) -> None:
    """Test successful re-authentication."""
    # Arrange
    router_ip = "192.168.1.1"
    credentials = {"router_userid": "admin", "router_password": "pw"}
    mock_session = MagicMock(spec=requests.Session)
    mock_router_login.return_value = mock_session

    # Act
    session = re_authenticate(router_ip, credentials)

    # Assert
    assert session == mock_session
    mock_router_login.assert_called_once_with(
        router_ip, credentials["router_userid"], credentials["router_password"]
    )


@patch("src.router_utils.router_login")
def test_re_authenticate_failure(mock_router_login: MagicMock) -> None:
    """Test re-authentication failure."""
    # Arrange
    router_ip = "192.168.1.1"
    credentials = {"router_userid": "admin", "router_password": "pw"}
    mock_router_login.side_effect = RuntimeError("Login failed")

    # Act & Assert
    with pytest.raises(RuntimeError, match="Login failed"):
        re_authenticate(router_ip, credentials)
