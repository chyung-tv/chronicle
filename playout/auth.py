"""Session stub. Swap get_user() for better-auth / Auth.js later.

Callers should depend on User, not on cookies or headers directly.
When auth is wired: read the session (cookie / Authorization) and return
the same User shape. DEV_USER_ID is only the unsigned fallback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Request

# better-auth / Auth.js: replace with the signed-in user's id.
DEV_USER_ID = os.getenv("PLAYOUT_DEV_USER_ID", "dev-owner")
DEV_USER_NAME = os.getenv("PLAYOUT_DEV_USER_NAME", "開發者")


@dataclass(frozen=True)
class User:
    id: str
    name: str


def get_user(request: Request | None = None) -> User:
    """Current user. Header, then cookie, then the unsigned dev identity."""
    uid = ""
    name = ""
    if request is not None:
        uid = (request.headers.get("X-User-Id") or "").strip()
        name = (request.headers.get("X-User-Name") or "").strip()
        if not uid:
            uid = (request.cookies.get("playout_user") or "").strip()
        if not name:
            name = (request.cookies.get("playout_name") or "").strip()
    if not uid:
        uid = DEV_USER_ID
        name = name or DEV_USER_NAME
    return User(id=uid, name=name or uid)


def is_owner(user: User, owner_id: str) -> bool:
    return user.id == owner_id


def can_god(user: User, owner_id: str, status: str) -> bool:
    return status == "live" and is_owner(user, owner_id)
