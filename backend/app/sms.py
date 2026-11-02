"""SMS provider interface. Only a mock outbox exists for the prototype.

Real Indian SMS delivery needs a DLT-registered sender ID and pre-approved
templates, and Kannada text must be sent as Unicode (70 chars/segment). Swap
`MockSmsProvider` for a gateway implementation without touching callers.
"""
from __future__ import annotations

from sqlmodel import Session

from .models import SmsMessage


class MockSmsProvider:
    def send(self, session: Session, to_mobile: str, body: str, kind: str = "INFO") -> None:
        session.add(SmsMessage(to_mobile=to_mobile, body=body, kind=kind))
        session.commit()


provider = MockSmsProvider()

# Illustrative wording. Must be reviewed by a Kannada-speaking agricultural expert before real use.
NOTIFY_KN = (
    "ನಮಸ್ಕಾರ ರೈತರೇ! ನಿಮ್ಮ {crop_kn} ಬೆಳೆಯ ಸಮೀಕ್ಷೆ ಪೂರ್ಣಗೊಂಡಿದೆ. "
    "ನಿಮ್ಮ ಜಮೀನಿನಲ್ಲಿ ಪರಿಶೀಲಿಸಬೇಕಾದ ಕೆಲವು ಪ್ರದೇಶಗಳು ಕಂಡುಬಂದಿವೆ. "
    "ವರದಿ ಪಡೆಯಲು {point} ಸಂಪರ್ಕಿಸಿ. Farmer ID: {fid}. - AgriScout AI"
)
NOTIFY_KN_CLEAR = (
    "ನಮಸ್ಕಾರ ರೈತರೇ! ನಿಮ್ಮ {crop_kn} ಬೆಳೆಯ ಸಮೀಕ್ಷೆ ಪೂರ್ಣಗೊಂಡಿದೆ. "
    "ಯಾವುದೇ ಗಮನಾರ್ಹ ಸಮಸ್ಯೆ ಕಂಡುಬಂದಿಲ್ಲ. ವರದಿ ಪಡೆಯಲು {point} ಸಂಪರ್ಕಿಸಿ. "
    "Farmer ID: {fid}. - AgriScout AI"
)
NOTIFY_EN = (
    "AgriScout: your {crop} survey is complete. {finding} Collect your report at {point}. "
    "Farmer ID: {fid}."
)


CROP_KN = {"paddy": "ಭತ್ತದ", "maize": "ಮೆಕ್ಕೆಜೋಳದ"}  # needs review by a Kannada-speaking agricultural expert


def notify_text(language: str, has_hotspots: bool, point: str, farmer_id: str, crop: str = "Paddy") -> str:
    point = point or "nearest service centre / FPO office"
    if language == "kn":
        tpl = NOTIFY_KN if has_hotspots else NOTIFY_KN_CLEAR
        return tpl.format(point=point, fid=farmer_id, crop_kn=CROP_KN.get(crop.lower(), ""))
    finding = "Some areas need inspection." if has_hotspots else "No significant problem areas found."
    return NOTIFY_EN.format(finding=finding, point=point, fid=farmer_id, crop=crop.lower())


def otp_text(otp: str, purpose: str, centre: str = "") -> str:
    if purpose == "assisted":
        return (
            f"AgriScout OTP {otp}. Share only with the operator at {centre} to release YOUR report. "
            f"Valid 5 min. If you did not ask, ignore."
        )
    return f"AgriScout login OTP {otp}. Valid 5 min. Do not share."
