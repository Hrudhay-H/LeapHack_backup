from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def now() -> datetime:
    """Timezone-aware UTC. SQLModel stores/returns aware UTC datetimes."""
    return datetime.now(timezone.utc)


class Farmer(SQLModel, table=True):
    id: str = Field(primary_key=True)  # e.g. MDY-001
    name: str
    village: str
    language: str = "kn"
    mobile: str
    access_mode: str = "BOTH"  # DIGITAL | ASSISTED | BOTH
    sms_consent: bool = True
    collection_point: str = ""


class Operator(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    centre: str
    pin_salt: str
    pin_hash: str


class Farm(SQLModel, table=True):
    id: str = Field(primary_key=True)
    farmer_id: str = Field(foreign_key="farmer.id", index=True)
    name: str
    crop: str = "Paddy"


class Survey(SQLModel, table=True):
    id: str = Field(primary_key=True)
    farm_id: str = Field(foreign_key="farm.id", index=True)
    status: str = "PROCESSING"  # PROCESSING | COMPLETED | FAILED
    stage: str = ""  # current pipeline stage while PROCESSING (see simulation.STAGES)
    created_at: datetime = Field(default_factory=now)
    run_dir: str = ""
    data_source: str = "real"
    summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    error: Optional[str] = None


class Hotspot(SQLModel, table=True):
    pk: Optional[int] = Field(default=None, primary_key=True)
    survey_id: str = Field(foreign_key="survey.id", index=True)
    hotspot_id: str
    props: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    geometry: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    verdict: Optional[str] = None  # PEST | NOT_PEST | OTHER
    verdict_note: str = ""
    verdict_by: str = ""
    verdict_at: Optional[datetime] = None


class Report(SQLModel, table=True):
    id: str = Field(primary_key=True)
    survey_id: str = Field(foreign_key="survey.id", index=True)
    farmer_id: str = Field(foreign_key="farmer.id", index=True)
    version: int = 1
    path: str
    generated_at: datetime = Field(default_factory=now)


class SessionToken(SQLModel, table=True):
    token_hash: str = Field(primary_key=True)
    subject_type: str  # FARMER | OPERATOR
    subject_id: str
    expires_at: datetime


class LoginChallenge(SQLModel, table=True):
    id: str = Field(primary_key=True)
    farmer_id: str
    otp_hash: str
    expires_at: datetime
    attempts: int = 0
    status: str = "PENDING"  # PENDING | VERIFIED | EXPIRED | LOCKED


class AccessRequest(SQLModel, table=True):
    id: str = Field(primary_key=True)
    farmer_id: str = Field(index=True)
    report_id: str
    operator_id: str
    otp_hash: str
    expires_at: datetime
    attempts: int = 0
    verified_at: Optional[datetime] = None
    status: str = "PENDING"  # PENDING | VERIFIED | EXPIRED | LOCKED | REVOKED
    access_token_hash: Optional[str] = None
    access_expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now)


class AccessLog(SQLModel, table=True):
    pk: Optional[int] = Field(default=None, primary_key=True)
    farmer_id: str
    report_id: str
    actor_type: str  # FARMER | OPERATOR
    actor_id: str
    access_type: str  # VIEW | DOWNLOAD
    authorization_id: str = ""  # AccessRequest id, or SELF
    at: datetime = Field(default_factory=now)


class SmsMessage(SQLModel, table=True):
    """Outbox. In production a real gateway delivers these; in demo they are shown on a phone simulator."""

    pk: Optional[int] = Field(default=None, primary_key=True)
    to_mobile: str = Field(index=True)
    sender: str = "AGRISCT"
    body: str
    kind: str = "INFO"  # OTP | NOTIFY | INFO
    at: datetime = Field(default_factory=now)
