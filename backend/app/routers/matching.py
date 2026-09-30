from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import serializers as ser
from ..db import get_db
from ..models import HelpRequest, Match, User
from ..schemas import MatchFindIn
from ..security import current_user
from ..services import circle as circle_svc
from ..services import orchestrator as orch
from ..services import smartmatch
from .requests import flow

router = APIRouter(prefix="/api/matching", tags=["matching"])


def _owned_open(db: Session, rid: int, user: User) -> HelpRequest:
    req = db.get(HelpRequest, rid)
    if req is None or (req.requester_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Request not found")
    return req


def _match_out(db: Session, req: HelpRequest, m: smartmatch.MatchResult, requester: User) -> dict:
    # The requester may see how their OWN contacts relate to them; helpers never see this.
    label = circle_svc.helper_label(db, requester, m.helper.id, reveal=True) if m.in_circle else "Verified nearby helper"
    return {
        "helper": ser.helper_public(db, m.helper), "match_score": m.match_score, "trust_score": m.trust_score,
        "category_trust": m.category_trust, "distance_km": m.distance_km, "eta_minutes": m.eta_minutes,
        "in_circle": m.in_circle, "relationship_priority": m.relationship_priority, "relationship_label": label,
        "reasons": m.reasons, "skills_matched": m.skills_matched, "breakdown": m.breakdown,
    }


def _ranked(db: Session, req: HelpRequest, requester: User, limit: int) -> list[dict]:
    res = smartmatch.rank(db, req, limit=limit, radius_km=req.search_radius_km)
    db.add_all([Match(request_id=req.id, helper_id=m.helper.id, match_score=m.match_score, trust_score=m.trust_score,
                      distance_km=m.distance_km, eta_minutes=m.eta_minutes, in_circle=m.in_circle, breakdown=m.breakdown) for m in res])
    return [_match_out(db, req, m, requester) for m in res]


@router.post("/find")
def find(body: MatchFindIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req = _owned_open(db, body.request_id, user)
    requester = db.get(User, req.requester_id)
    out = _ranked(db, req, requester, body.limit)
    db.commit()
    return {"request_id": req.id, "matches": out}


@router.get("/{request_id}")
def get_matches(request_id: int, limit: int = 10, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req = _owned_open(db, request_id, user)
    requester = db.get(User, req.requester_id)
    out = _ranked(db, req, requester, max(1, min(limit, 25)))
    db.commit()
    return {"request_id": req.id, "matches": out}


@router.post("/{request_id}/invite/{helper_id}")
def invite(request_id: int, helper_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Requester picks a specific helper from the ranked list."""
    req = _owned_open(db, request_id, user)
    flow(lambda: orch.invite_helper(db, req, user, helper_id), db)
    db.commit()
    return {"status": "notified"}


@router.post("/{request_id}/accept")
def accept(request_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A notified helper accepts. Race-safe: only one acceptance wins each open slot."""
    asg = flow(lambda: orch.helper_accept(db, request_id, user), db)
    db.commit()
    req = db.get(HelpRequest, request_id)
    return {"assignment_id": asg.id, "eta_minutes": asg.eta_minutes, "distance_km": asg.distance_km,
            "request": ser.request_out(db, req, user, "helper")}


@router.post("/{request_id}/reject")
def reject(request_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    flow(lambda: orch.helper_decline(db, request_id, user), db)
    db.commit()
    return {"status": "declined"}
