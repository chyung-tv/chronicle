"""Session stub. Swap get_user() for better-auth / Auth.js later.

Callers should depend on User, not on cookies or headers directly.
When auth is wired: read the session (cookie / Authorization) and return
the same User shape.

Unsigned visitors are the audience, not the seeded owner. DEV_USER_ID is
only the Harbor's End seed owner (and an explicit header/cookie).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Request

# better-auth / Auth.js: replace with the signed-in user's id.
DEV_USER_ID = os.getenv("PLAYOUT_DEV_USER_ID", "dev-owner")
DEV_USER_NAME = os.getenv("PLAYOUT_DEV_USER_NAME", "開發者")
GUEST_USER_ID = os.getenv("PLAYOUT_GUEST_USER_ID", "audience")
GUEST_USER_NAME = os.getenv("PLAYOUT_GUEST_USER_NAME", "訪客")


@dataclass(frozen=True)
class User:
    id: str
    name: str


def get_user(request: Request | None = None) -> User:
    """Current user. Header, then cookie, then the unsigned guest identity."""
    uid = ""
    name = ""
    if request is not None:
        uid = (request.headers.get("X-User-Id") or "").strip()
        name = (request.headers.get("X-User-Name") or "").strip()
        if not uid:
            uid = (request.cookies.get("playout_user") or "").strip()
    if not uid:
        uid = GUEST_USER_ID
        name = name or GUEST_USER_NAME
    if not name:
        if uid == GUEST_USER_ID or uid.startswith("guest-"):
            name = GUEST_USER_NAME
        else:
            name = uid
    return User(id=uid, name=name)


def is_owner(user: User, owner_id: str) -> bool:
    return user.id == owner_id


def can_god(user: User, owner_id: str, status: str) -> bool:
    return status == "live" and is_owner(user, owner_id)


def can_tick(user: User, owner_id: str, status: str) -> bool:
    """Readers never advance time. Owner (or a system job) only."""
    return can_god(user, owner_id, status)
