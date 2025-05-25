"""Utility module for password hashing using bcrypt."""

import bcrypt  # pylint: disable=import-error


def hash_password(plain_password: str) -> str:
    """
    Generates a bcrypt hashed password.

    Args:
        plain_password (str): The plaintext password to hash.

    Returns:
        str: The bcrypt hashed password.
    """
    # Generate a salted hash for the password
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password.encode(), salt)
    return str(hashed.decode())


if __name__ == "__main__":
    password = input("Enter password to hash: ")
    HASHED = hash_password(password)
    print(f"Hashed password: {HASHED}")
