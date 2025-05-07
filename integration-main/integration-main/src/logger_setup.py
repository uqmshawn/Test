"""Logger setup for the application."""

import os
import logging
from logging.handlers import RotatingFileHandler

# Create directory for logs if not exists
LOG_DIR = os.environ.get("LOG_DIR", "/app/logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Use environment variable to determine process-specific log file name
process_name = os.environ.get("PROCESS_NAME", "default")
log_file = os.path.join(LOG_DIR, f"{process_name}.log")

# New formatter string with file and line number
formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s"
)

# Configure Rotating File Handler
file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
file_handler.setFormatter(formatter)

# Configure stream handler (same formatter)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])


def set_process_name(name: str) -> None:
    """Update the process-specific log file.

    Args:
        name: Name of the process for the log file
    """
    new_log_file = os.path.join(LOG_DIR, f"{name}.log")
    root_logger = logging.getLogger()
    # Remove existing RotatingFileHandler(s)
    for h in root_logger.handlers[:]:
        if hasattr(h, "baseFilename"):
            root_logger.removeHandler(h)
    # Create and add new file handler with the updated log file name
    new_file_handler = RotatingFileHandler(
        new_log_file, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    new_file_handler.setFormatter(formatter)
    root_logger.addHandler(new_file_handler)
