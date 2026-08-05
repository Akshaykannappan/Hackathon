"""Request bodies for the auth forms.

The routes render HTML forms, but the submitted values are still validated
through pydantic before anything reaches the database (CONTEXT §8).
"""

import re

from pydantic import BaseModel, Field, field_validator

MIN_PASSWORD_LENGTH = 8

# Deliberately permissive: enough to catch a typo, not an RFC 5322 parser.
# `email-validator` is not a project dependency, so EmailStr is unavailable.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    """Credentials submitted by the login form."""

    email: str = Field(max_length=255)
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_RE.match(value):
            raise ValueError("Enter a valid email address.")
        return value


class RegisterRequest(LoginRequest):
    """A new account. Password length is bounded by bcrypt's 72-byte limit."""

    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=72)

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password is too long (72 bytes maximum).")
        if value.strip() == "":
            raise ValueError("Password cannot be blank.")
        return value
