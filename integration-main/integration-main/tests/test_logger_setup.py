"""Tests for logger_setup.py functions."""

import pytest
from unittest.mock import patch, MagicMock
import os
import logging
from logging.handlers import RotatingFileHandler
from src.logger_setup import set_process_name


@pytest.fixture
def mock_logger():
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
def mock_makedirs():
    with patch("src.logger_setup.os.makedirs") as mock:
        yield mock


@pytest.fixture
def mock_path_join():
    with patch(
        "src.logger_setup.os.path.join", return_value="/test/path/test.log"
    ) as mock:
        yield mock


@pytest.fixture
def mock_rotating_file_handler():
    with patch("src.logger_setup.RotatingFileHandler") as mock_handler_class:
        mock_instance = MagicMock()
        mock_instance.baseFilename = "/test/path/test.log"
        mock_handler_class.return_value = mock_instance
        yield mock_handler_class


def test_set_process_name(
    mock_logger, mock_makedirs, mock_path_join, mock_rotating_file_handler
):
    # Create a mock handler
    old_handler = MagicMock()
    old_handler.baseFilename = "/old/path/test.log"
    mock_logger.handlers = [old_handler]

    set_process_name("test_process")

    # Get all calls to removeHandler that involved our mock handler
    remove_calls = [
        call
        for call in mock_logger.removeHandler.call_args_list
        if call.args[0] == old_handler
    ]
    assert len(remove_calls) == 1

    # Get all calls to addHandler that involved a RotatingFileHandler
    add_calls = [
        call
        for call in mock_logger.addHandler.call_args_list
        if hasattr(call.args[0], "baseFilename")
    ]
    assert len(add_calls) == 1
    new_handler = add_calls[0].args[0]
    assert new_handler.baseFilename == "/test/path/test.log"


def test_set_process_name_no_existing_handlers(
    mock_logger, mock_makedirs, mock_path_join, mock_rotating_file_handler
):
    mock_logger.handlers = []

    set_process_name("test_process")

    # Get all calls to removeHandler that involved handlers with baseFilename
    remove_calls = [
        call
        for call in mock_logger.removeHandler.call_args_list
        if hasattr(call.args[0], "baseFilename")
    ]
    assert len(remove_calls) == 0

    # Get all calls to addHandler that involved a RotatingFileHandler
    add_calls = [
        call
        for call in mock_logger.addHandler.call_args_list
        if hasattr(call.args[0], "baseFilename")
    ]
    assert len(add_calls) == 1
    new_handler = add_calls[0].args[0]
    assert new_handler.baseFilename == "/test/path/test.log"


def test_set_process_name_multiple_file_handlers(
    mock_logger, mock_makedirs, mock_path_join, mock_rotating_file_handler
):
    # Create multiple mock handlers
    handler1 = MagicMock()
    handler1.baseFilename = "/old/path/test1.log"
    handler2 = MagicMock()
    handler2.baseFilename = "/old/path/test2.log"
    mock_logger.handlers = [handler1, handler2]

    set_process_name("test_process")

    # Get all calls to removeHandler that involved our mock handlers
    remove_calls = [
        call
        for call in mock_logger.removeHandler.call_args_list
        if call.args[0] in [handler1, handler2]
    ]
    assert len(remove_calls) == 2
    assert any(call.args[0] == handler1 for call in remove_calls)
    assert any(call.args[0] == handler2 for call in remove_calls)

    # Get all calls to addHandler that involved a RotatingFileHandler
    add_calls = [
        call
        for call in mock_logger.addHandler.call_args_list
        if hasattr(call.args[0], "baseFilename")
    ]
    assert len(add_calls) == 1
    new_handler = add_calls[0].args[0]
    assert new_handler.baseFilename == "/test/path/test.log"
