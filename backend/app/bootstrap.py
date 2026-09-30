"""Idempotent creation of schema + reference data (safe to run on every startup)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import protocols_data as pd
from . import taxonomy as tx
from .db import Base, engine
from .models import (
    Certification, Protocol, ProtocolStep, RelationshipType, RequestCategory, Skill,
)


def init_schema() -> None:
    Base.metadata.create_all(engine)


def ensure_reference_data(db: Session) -> None:
    existing = {c.slug for c in db.scalars(select(RequestCategory))}
    for slug, label, skills, icon in tx.CATEGORIES:
        if slug not in existing:
            db.add(RequestCategory(slug=slug, label=label, default_skills=skills, icon=icon))

    existing = {s.slug for s in db.scalars(select(Skill))}
    for slug, label, cat in tx.SKILLS:
        if slug not in existing:
            db.add(Skill(slug=slug, label=label, trust_category=cat))

    existing = {c.slug for c in db.scalars(select(Certification))}
    for slug, label, grants in tx.CERTIFICATIONS:
        if slug not in existing:
            db.add(Certification(slug=slug, label=label, grants_skill=grants))

    existing = {r.slug for r in db.scalars(select(RelationshipType))}
    for slug, label, group, inverse in tx.RELATIONSHIP_TYPES:
        if slug not in existing:
            db.add(RelationshipType(slug=slug, label=label, group=group, inverse_slug=inverse))

    have = {p.slug for p in db.scalars(select(Protocol))}
    for slug, title, kws, needs_em, steps in pd.PROTOCOLS:
        if slug in have:
            continue
        proto = Protocol(slug=slug, version=1, title=title, situation_keywords=kws,
                         requires_emergency_services=needs_em, source=pd.SOURCE)
        for i, (ins, fb, crit) in enumerate(steps, start=1):
            proto.steps.append(ProtocolStep(position=i, instruction=ins, fallback_instruction=fb, is_critical=crit))
        db.add(proto)
    db.commit()
