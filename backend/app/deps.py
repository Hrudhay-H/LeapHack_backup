from __future__ import annotations

import os

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session

from .db import get_session
from .models import Farmer, Operator, SessionToken
from .security import expired, hash_token

ADMIN_KEY = os.environ.get("AGRISCOUT_ADMIN_KEY", "demo-admin")
DEMO_MODE = os.environ.get("AGRISCOUT_DEMO", "1") == "1"


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def _subject(session: Session, authorization: str | None, kind: str) -> str:
    st = session.get(SessionToken, hash_token(_bearer(authorization)))
    if not st or st.subject_type != kind or expired(st.expires_at):
        raise HTTPException(401, "Invalid or expired session")
    return st.subject_id


def current_farmer(authorization: str | None = Header(None), session: Session = Depends(get_session)) -> Farmer:
    return session.get(Farmer, _subject(session, authorization, "FARMER"))


def current_operator(authorization: str | None = Header(None), session: Session = Depends(get_session)) -> Operator:
    return session.get(Operator, _subject(session, authorization, "OPERATOR"))


def actor(authorization: str | None = Header(None), session: Session = Depends(get_session)) -> tuple[str, str]:
    """Farmer or operator (used for scout verdicts)."""
    st = session.get(SessionToken, hash_token(_bearer(authorization)))
    if not st or expired(st.expires_at):
        raise HTTPException(401, "Invalid or expired session")
    return st.subject_type, st.subject_id


def require_admin(x_admin_key: str | None = Header(None)) -> None:
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(403, "Admin key required")
