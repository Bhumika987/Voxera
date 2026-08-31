"""Minimal JWT auth for the Voxera API.

One hardcoded "manager" account whose credentials live in ``backend/.env``
(a username plus a bcrypt hash of the password) — not the database. A single
role, no permission system: a valid, unexpired token is all any protected
route checks for.

Notes
-----
* We use the ``bcrypt`` package directly rather than ``passlib`` because
  ``chromadb`` already pins ``bcrypt>=5``, and ``passlib==1.7.4`` cannot
  drive that version (its backend probe crashes on the removed
  ``bcrypt.__about__``). ``bcrypt`` alone covers everything we need here.
* Tokens are signed with ``JWT_SECRET_KEY`` from ``.env`` and expire after
  ``ACCESS_TOKEN_EXPIRE_HOURS`` (8h).
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

# backend/app/auth.py -> backend/app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / "backend" / ".env")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-insecure-secret-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8

MANAGER_USERNAME = os.getenv("MANAGER_USERNAME", "")
MANAGER_PASSWORD_HASH = os.getenv("MANAGER_PASSWORD_HASH", "")

# auto_error=False so we can return a consistent JSON 401 (and so the audio
# route can fall back to a query-string token — see verify_token_flexible).
# The scheme is still advertised in the OpenAPI spec, so Swagger UI shows the
# "Authorize" button where a bearer token can be pasted.
_bearer_scheme = HTTPBearer(auto_error=False, description="Paste the JWT returned by POST /api/auth/login")

_credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Constant-time bcrypt check. Returns False on any malformed input."""
    if not plain_password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def authenticate_manager(username: str, password: str) -> bool:
    """True only for the single configured manager account."""
    # Look up the module globals at call time so tests can monkeypatch them.
    expected_user = MANAGER_USERNAME
    expected_hash = MANAGER_PASSWORD_HASH
    if not expected_user or not expected_hash:
        return False
    return username == expected_user and verify_password(password, expected_hash)


def create_access_token(subject: str) -> str:
    """Sign a token for ``subject`` (the username), expiring in 8 hours."""
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> str:
    """Return the token subject, or raise 401."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise _credentials_exception
    subject = payload.get("sub")
    if not subject:
        raise _credentials_exception
    return subject


def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency — attach with ``Depends(verify_token)`` to protect a route.

    Reads ``Authorization: Bearer <token>``. Returns the username on success,
    raises 401 otherwise.
    """
    if credentials is None or not credentials.credentials:
        raise _credentials_exception
    return _decode_token(credentials.credentials)


def verify_token_flexible(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    token: str | None = Query(default=None, description="JWT, for clients that cannot set headers (e.g. <audio> tags)"),
) -> str:
    """Like :func:`verify_token`, but also accepts the token as a ``?token=``
    query parameter.

    Needed only for ``GET /api/calls/{id}/audio``: the browser loads that URL
    through an ``<audio src>`` element, which cannot carry an Authorization
    header.
    """
    raw = credentials.credentials if credentials and credentials.credentials else token
    if not raw:
        raise _credentials_exception
    return _decode_token(raw)
