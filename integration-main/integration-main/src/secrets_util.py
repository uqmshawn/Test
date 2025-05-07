"""Utility module for loading application secrets from TOML files."""

import logging
import toml


def load_secrets(secrets_path: str = "/app/.secrets/secrets.toml") -> dict[str, str]:
    """Load secrets from a TOML file at the specified path."""
    logging.info("Looking for secrets file at: %s", secrets_path)
    try:
        with open(secrets_path, "r", encoding="utf-8") as f:
            content = f.read()
            logging.info("File content length: %d bytes", len(content))
            return dict(toml.loads(content))
    except FileNotFoundError:
        logging.error("Secrets file not found at: %s", secrets_path)
    except Exception as e:
        logging.error("Error loading secrets: %s", str(e))
        logging.exception("Full traceback:")
    return {}
