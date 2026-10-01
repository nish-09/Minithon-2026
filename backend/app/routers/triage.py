from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Incident, User
from ..schemas import Strict
from ..security import current_user
from ..services import care, triage

router = APIRouter(prefix="/api/triage", tags=["nexa-care"])


class AssessIn(Strict):
    text: str = Field(default="", max_length=500)
    observations: list[str] = Field(default_factory=list, max_length=20)
    answers: dict[str, bool] = Field(default_factory=dict)
    incident_id: int | None = None


class VisionIn(Strict):
    image_b64: str = Field(min_length=100, max_length=600_000)  # one small JPEG frame
    media_type: str = Field(default="image/jpeg", pattern="^image/(jpeg|png|webp)$")
    consent: bool


@router.post("/assess")
def assess(body: AssessIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Conservative triage from description + observations + answers. Not a diagnosis."""
    result = triage.assess(body.text, body.observations, body.answers)
    if body.incident_id is not None:
        inc = db.get(Incident, body.incident_id)
        if inc is None or inc.user_id != user.id:
            raise HTTPException(404, "Incident not found")
        # audit the level and observable factors only: never images
        care.audit(db, inc.id, "triage", "nexa", f"{result.level}: " + "; ".join(result.reasons[:4]),
                   meta={"level": result.level, "red_flags": result.red_flags})
        if result.level == "CRITICAL" and inc.status == "ACTIVE" and not inc.emergency_services_advised:
            care.escalate(db, inc, False, "triage red flag: " + ", ".join(result.red_flags)[:150])
        db.commit()
    return {**result.to_dict(), "suggest_visual": triage.needs_visual_assessment(body.text)}


@router.post("/vision")
def vision(body: VisionIn, user: User = Depends(current_user)):
    """One frame, sent only after explicit consent, analysed and discarded (not stored, not logged)."""
    if not body.consent:
        raise HTTPException(403, "Camera analysis needs your explicit consent")
    return triage.vision_observe(body.image_b64, body.media_type)
