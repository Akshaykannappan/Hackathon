"""Password hashing and signed session cookies.

Auth is deliberately simple per the brief (CONTEXT §3): bcrypt for passwords,
a signed cookie for the session. No JWTs, no server-side session store.
"""

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.responses import Response

from app.core.config import settings

SESSION_COOKIE_NAME = "smartreco_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14  # 14 days

# bcrypt silently truncates at 72 bytes; reject longer input rather than
# accepting a password whose tail is never checked.
MAX_PASSWORD_BYTES = 72

_serializer = URLSafeTimedSerializer(
    settings.session_secret,
    salt="smartreco.session.v1",
)


def hash_password(password: str) -> str:
    """Return a bcrypt hash of `password`."""
    pw_bytes = password.encode("utf-8")
    if len(pw_bytes) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password exceeds bcrypt's {MAX_PASSWORD_BYTES}-byte limit."
        )
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check `password` against a stored hash. Never raises on bad input."""
    try:
        pw_bytes = password.encode("utf-8")
        hash_bytes = password_hash.encode("utf-8")
        return bcrypt.checkpw(pw_bytes, hash_bytes)
    except (ValueError, TypeError):
        # Malformed or truncated hash in the database — treat as a failed login.
        return False


def sign_session(user_id: int) -> str:
    """Serialise a user id into a tamper-proof, timestamped cookie value."""
    return _serializer.dumps({"user_id": user_id})


def read_session(token: str) -> int | None:
    """Return the user id carried by `token`, or None if it is not usable.

    Covers a forged signature, an expired cookie, and a cookie signed with a
    previous SESSION_SECRET — all of which simply mean "logged out".
    """
    try:
        payload = _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    user_id = payload.get("user_id")
    return user_id if isinstance(user_id, int) else None


def set_session_cookie(response: Response, user_id: int) -> None:
    """Attach a signed session cookie to `response`."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        sign_session(user_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie from the browser."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
