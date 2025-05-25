"""Utility module for loading application secrets from TOML files."""

import logging
import toml
import re


def load_secrets(secrets_path: str = "/app/.secrets/secrets.toml") -> dict[str, str]:
    """Load secrets from a TOML file at the specified path."""
    logging.info("Looking for secrets file at: %s", secrets_path)
    try:
        with open(secrets_path, "r", encoding="utf-8") as f:
            content = f.read()
            logging.info("File content length: %d bytes", len(content))

            # Log structure of the file (without exposing sensitive data)
            safe_content = re.sub(
                r'(admin|router_password|password) = "([^"]*)"',
                r'\1 = "***MASKED***"',
                content,
            )
            logging.info("File structure: \n%s", safe_content)

            # Check for bcrypt hash format in admin password
            admin_match = re.search(r'admin = "([^"]*)"', content)
            if admin_match:
                admin_pw = admin_match.group(1)
                if admin_pw.startswith("$2b$"):
                    logging.info(
                        "Admin password appears to be in correct bcrypt format"
                    )
                else:
                    logging.warning(
                        "Admin password does not appear to be in correct bcrypt format"
                    )

            # Parse TOML
            parsed_content = toml.loads(content)
            logging.info(
                "Successfully parsed TOML file with %d sections", len(parsed_content)
            )
            return dict(parsed_content)
    except FileNotFoundError:
        logging.error("Secrets file not found at: %s", secrets_path)
    except toml.TomlDecodeError as e:
        logging.error("TOML parsing error: %s", str(e))
        logging.exception("Full traceback:")
    except Exception as e:
        logging.error("Error loading secrets: %s", str(e))
        logging.exception("Full traceback:")
    return {}
