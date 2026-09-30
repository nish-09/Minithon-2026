"""AI-assisted, explainable Trust Engine.

Architecture
  TrustFeatures  <- collected from the DB (identity, skills, behaviour, community evidence)
  TrustModel     <- pluggable scorer (Protocol). Default: HeuristicTrustModel (transparent, Bayesian-shrunk).
                    A LightGBM/XGBoost/RandomForest model can be dropped in via `set_model()` once real
                    labelled outcome data exists; it must return the same TrustResult (incl. explanation).
  TrustResult    <- overall score, components, contextual (per-category) scores, human-readable factors.

Trust is an *indicator based on available evidence*, never a guarantee. Sparse evidence lowers
`confidence` and pulls behaviour components toward a neutral prior instead of rewarding or punishing
new users by default.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Report, Review, Skill, TrustEvent, TrustScore, User, UserCertification, utcnow,
)

PRIOR = 50.0
MODEL_VERSION = "heuristic-v1"

COMPONENT_WEIGHTS = {
    "verification": 0.25,
    "response_reliability": 0.25,
    "community_reputation": 0.25,
    "help_history": 0.15,
    "credentials": 0.10,
}
COMPONENT_LABELS = {
    "verification": "Verification",
    "response_reliability": "Response Reliability",
    "community_reputation": "Community Reputation",
    "help_history": "Help History",
    "credentials": "Skills & Credentials",
}


@dataclass
class TrustFeatures:
    phone_verified: bool = False
    email_verified: bool = False
    identity_verified: bool = False
    account_age_days: float = 0
    profile_completeness: float = 0  # 0..1
    verified_certs: int = 0
    unverified_certs: int = 0
    skill_count: int = 0
    notified: int = 0
    responded: int = 0
    accepted: int = 0
    declined: int = 0
    avg_response_s: float | None = None
    completed: int = 0
    cancelled: int = 0
    no_shows: int = 0
    rating_avg: float | None = None
    rating_count: int = 0
    reports_upheld: int = 0
    repeat_partners: int = 0
    category_completed: dict[str, int] = field(default_factory=dict)
    category_rating: dict[str, tuple[float, int]] = field(default_factory=dict)  # cat -> (avg, n)
    category_credentials: dict[str, float] = field(default_factory=dict)  # cat -> bonus


@dataclass
class Factor:
    key: str
    label: str
    impact: str  # positive | negative | neutral
    detail: str


@dataclass
class TrustResult:
    user_id: int
    score: float
    confidence: float
    components: dict[str, float]
    categories: dict[str, float]
    factors: list[Factor]
    badges: list[str]
    model_version: str = MODEL_VERSION
    stats: dict = field(default_factory=dict)


class TrustModel(Protocol):
    version: str

    def score(self, f: TrustFeatures, categories: list[str]) -> TrustResult: ...


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _shrink(raw: float, n: float, k: float) -> float:
    """Bayesian-style shrinkage toward the neutral prior: weight n/(n+k) on evidence."""
    w = n / (n + k)
    return w * raw + (1 - w) * PRIOR


class HeuristicTrustModel:
    version = MODEL_VERSION

    def score(self, f: TrustFeatures, categories: list[str]) -> TrustResult:
        factors: list[Factor] = []

        # --- verification (real evidence; not shrunk)
        ver = 0.0
        ver += 30 if f.identity_verified else 0
        ver += 25 if f.phone_verified else 0
        ver += 20 if f.email_verified else 0
        ver += min(15, f.account_age_days / 365 * 15)
        ver += 10 * f.profile_completeness
        ver = _clamp(ver)
        if f.identity_verified:
            factors.append(Factor("identity", "Identity verified", "positive", "Identity was reviewed by an administrator."))
        else:
            factors.append(Factor("identity", "Identity not verified", "negative", "No verified identity on file yet."))
        if f.phone_verified:
            factors.append(Factor("phone", "Phone verified", "positive", "Phone number confirmed."))

        # --- response reliability
        if f.notified > 0:
            response_rate = f.responded / f.notified
        else:
            response_rate = None
        acceptance_rate = f.accepted / f.responded if f.responded else None
        cancel_rate = f.cancelled / (f.accepted or 1) if f.accepted else 0.0
        noshow_rate = f.no_shows / (f.accepted or 1) if f.accepted else 0.0
        if response_rate is None and not f.accepted:
            resp_raw, resp_n = PRIOR, 0.0
        else:
            rr = response_rate if response_rate is not None else 0.5
            speed = 1.0
            if f.avg_response_s is not None:
                speed = _clamp(1.15 - f.avg_response_s / 900.0, 0.3, 1.0)  # <~2 min => full marks
            raw = 100 * (0.45 * rr + 0.25 * speed + 0.30 * (1 - min(1.0, cancel_rate + noshow_rate * 2)))
            resp_raw, resp_n = raw, float(max(f.notified, f.accepted))
        resp = _clamp(_shrink(resp_raw, resp_n, 6))
        if response_rate is not None and f.notified >= 3:
            factors.append(Factor(
                "response", f"{round(response_rate * 100)}% response rate",
                "positive" if response_rate >= 0.7 else "negative",
                f"Responded to {f.responded} of {f.notified} requests sent to them."))
        if f.accepted and cancel_rate > 0.2:
            factors.append(Factor("cancel", "High cancellation rate", "negative",
                                  f"Cancelled {f.cancelled} of {f.accepted} accepted requests."))
        if f.no_shows:
            factors.append(Factor("noshow", "No-shows recorded", "negative", f"{f.no_shows} accepted request(s) not attended."))

        # --- community reputation
        if f.rating_count:
            rating_raw = (f.rating_avg - 1) / 4 * 100
        else:
            rating_raw = PRIOR
        rep = _shrink(rating_raw, f.rating_count, 5)
        rep += min(6.0, f.repeat_partners * 2.0)  # people who were helped again and again
        rep -= 25 * f.reports_upheld
        rep = _clamp(rep)
        if f.rating_count:
            factors.append(Factor("rating", f"{f.rating_avg:.1f}★ community rating",
                                  "positive" if f.rating_avg >= 4.2 else ("neutral" if f.rating_avg >= 3.5 else "negative"),
                                  f"Based on {f.rating_count} review(s)."))
        else:
            factors.append(Factor("rating", "No reviews yet", "neutral", "Score leans neutral until reviews exist."))
        if f.reports_upheld:
            factors.append(Factor("reports", "Upheld reports", "negative", f"{f.reports_upheld} report(s) upheld by moderators."))
        if f.repeat_partners:
            factors.append(Factor("repeat", "Helped the same people repeatedly", "positive",
                                  f"{f.repeat_partners} neighbour(s) were helped more than once."))

        # --- help history
        hist_raw = _clamp(f.completed * 6.0, 0, 100)
        hist = _clamp(_shrink(hist_raw, f.completed + 1, 3)) if f.completed else PRIOR * 0.6
        if f.completed:
            factors.append(Factor("completed", f"{f.completed} helps completed", "positive", "Completed requests on NEXA."))
        else:
            factors.append(Factor("completed", "No completed helps yet", "neutral", "Trust grows as help is completed."))

        # --- credentials
        cred = _clamp(f.verified_certs * 35 + f.unverified_certs * 5 + min(f.skill_count, 5) * 6)
        if f.verified_certs:
            factors.append(Factor("certs", f"{f.verified_certs} verified certification(s)", "positive",
                                  "Certifications confirmed by an administrator."))

        components = {
            "verification": round(ver, 1),
            "response_reliability": round(resp, 1),
            "community_reputation": round(rep, 1),
            "help_history": round(hist, 1),
            "credentials": round(cred, 1),
        }
        overall = sum(components[k] * w for k, w in COMPONENT_WEIGHTS.items())
        overall -= 6 * f.no_shows + (8 if f.cancelled > 2 and cancel_rate > 0.3 else 0)
        overall -= min(40.0, 10.0 * f.reports_upheld)  # upheld reports are direct evidence of harm, not just reputation
        overall = round(_clamp(overall), 1)

        evidence = f.notified + f.completed * 2 + f.rating_count * 2
        confidence = round(min(1.0, evidence / 20), 2)
        if confidence < 0.3:
            factors.append(Factor("confidence", "Limited history", "neutral",
                                  "Few interactions so far; this score is provisional."))

        # --- contextual (per-category) trust: never inherits the overall score wholesale
        cats: dict[str, float] = {}
        for cat in categories:
            n_done = f.category_completed.get(cat, 0)
            r_avg, r_n = f.category_rating.get(cat, (0.0, 0))
            cred_bonus = f.category_credentials.get(cat, 0.0)
            base = min(overall, 40.0) + cred_bonus
            w = min(1.0, (n_done + r_n) / 5)
            perf = ((r_avg - 1) / 4 * 100) if r_n else overall
            val = (1 - w) * base + w * (0.6 * perf + 0.4 * overall) + min(10.0, n_done * 1.5) * w
            cats[cat] = round(_clamp(val), 1)

        badges = []
        if f.identity_verified:
            badges.append("identity_verified")
        if f.verified_certs:
            badges.append("certified")
        if f.completed >= 10:
            badges.append("experienced_helper")

        stats = {
            "response_rate": None if response_rate is None else round(response_rate * 100),
            "acceptance_rate": None if acceptance_rate is None else round(acceptance_rate * 100),
            "cancellation_rate": round(cancel_rate * 100) if f.accepted else None,
            "no_show_rate": round(noshow_rate * 100) if f.accepted else None,
            "avg_response_seconds": None if f.avg_response_s is None else round(f.avg_response_s),
            "completed": f.completed,
            "rating": None if f.rating_avg is None else round(f.rating_avg, 2),
            "review_count": f.rating_count,
        }
        return TrustResult(0, overall, confidence, components, cats, factors, badges, self.version, stats)


_model: TrustModel = HeuristicTrustModel()


def set_model(model: TrustModel) -> None:
    """Swap in a trained model (e.g. LightGBM wrapper) without touching callers."""
    global _model
    _model = model


def get_model() -> TrustModel:
    return _model


# ---- feature collection -------------------------------------------------------------------
def collect_features(db: Session, user: User) -> tuple[TrustFeatures, list[str]]:
    uid = user.id
    now = datetime.now(timezone.utc)
    created = user.created_at if user.created_at.tzinfo else user.created_at.replace(tzinfo=timezone.utc)
    p = user.profile
    completeness = sum([
        bool(user.phone), bool(user.avatar_url), bool(p and p.bio), bool(user.skills), user.lat is not None,
    ]) / 5

    f = TrustFeatures(
        phone_verified=user.phone_verified, email_verified=user.email_verified,
        identity_verified=user.identity_verified, account_age_days=max(0.0, (now - created).total_seconds() / 86400),
        profile_completeness=completeness, skill_count=len(user.skills),
    )

    counts = dict(db.execute(
        select(TrustEvent.kind, func.count()).where(TrustEvent.user_id == uid).group_by(TrustEvent.kind)
    ).all())
    f.notified = counts.get("notified", 0)
    f.responded = counts.get("responded", 0)
    f.accepted = counts.get("accepted", 0)
    f.declined = counts.get("declined", 0)
    f.completed = counts.get("completed", 0)
    f.cancelled = counts.get("cancelled", 0)
    f.no_shows = counts.get("no_show", 0)
    f.avg_response_s = db.scalar(
        select(func.avg(TrustEvent.value)).where(TrustEvent.user_id == uid, TrustEvent.kind == "responded")
    )
    for cat, n in db.execute(
        select(TrustEvent.category, func.count()).where(
            TrustEvent.user_id == uid, TrustEvent.kind == "completed", TrustEvent.category.is_not(None)
        ).group_by(TrustEvent.category)
    ):
        f.category_completed[cat] = n

    avg, n = db.execute(select(func.avg(Review.rating), func.count()).where(Review.reviewee_id == uid)).one()
    f.rating_count = n
    f.rating_avg = float(avg) if avg is not None else None
    for cat, a, cnt in db.execute(
        select(Review.category, func.avg(Review.rating), func.count()).where(
            Review.reviewee_id == uid, Review.category.is_not(None)
        ).group_by(Review.category)
    ):
        f.category_rating[cat] = (float(a), cnt)

    f.reports_upheld = db.scalar(
        select(func.count()).select_from(Report).where(Report.target_user_id == uid, Report.status == "UPHELD")
    ) or 0
    f.repeat_partners = db.scalar(
        select(func.count()).select_from(
            select(TrustEvent.counterparty_id).where(
                TrustEvent.user_id == uid, TrustEvent.kind == "completed", TrustEvent.counterparty_id.is_not(None)
            ).group_by(TrustEvent.counterparty_id).having(func.count() >= 2).subquery()
        )
    ) or 0

    # credentials: verified certs / declared skills bonus per trust category
    for uc in db.scalars(select(UserCertification).where(UserCertification.user_id == uid)):
        if uc.verified:
            f.verified_certs += 1
        else:
            f.unverified_certs += 1
    skill_cats = {s.slug: s.trust_category for s in db.scalars(select(Skill))}
    for us in user.skills:
        cat = us.skill.trust_category
        if cat:
            f.category_credentials[cat] = f.category_credentials.get(cat, 0) + 8 + min(us.years_experience, 5) * 1.5
    for uc in db.scalars(select(UserCertification).where(UserCertification.user_id == uid)):
        cat = skill_cats.get(uc.certification.grants_skill or "")
        if cat:
            f.category_credentials[cat] = f.category_credentials.get(cat, 0) + (25 if uc.verified else 4)
    for cat in list(f.category_credentials):
        f.category_credentials[cat] = min(45.0, f.category_credentials[cat])

    cats = sorted(set(f.category_credentials) | set(f.category_completed) | set(f.category_rating))
    return f, cats


def compute_trust(db: Session, user: User) -> TrustResult:
    f, cats = collect_features(db, user)
    res = get_model().score(f, cats)
    res.user_id = user.id
    return res


def refresh_trust(db: Session, user_id: int) -> TrustResult:
    user = db.get(User, user_id)
    res = compute_trust(db, user)
    now = utcnow()
    payload = {"components": res.components, "stats": res.stats, "badges": res.badges}
    rows = {r.category: r for r in db.scalars(select(TrustScore).where(TrustScore.user_id == user_id))}
    row = rows.get("") or TrustScore(user_id=user_id, category="", score=res.score)
    row.score, row.components, row.confidence, row.model_version, row.computed_at = (
        res.score, payload, res.confidence, res.model_version, now)
    db.merge(row)
    for cat, val in res.categories.items():
        r = rows.get(cat) or TrustScore(user_id=user_id, category=cat, score=val)
        r.score, r.model_version, r.computed_at, r.confidence = val, res.model_version, now, res.confidence
        db.merge(r)
    for cat in set(rows) - set(res.categories) - {""}:
        db.delete(rows[cat])
    db.flush()
    return res


def cached_scores(db: Session, user_ids: list[int]) -> dict[int, float]:
    """Overall scores for many users; computes+stores any that are missing."""
    if not user_ids:
        return {}
    have = dict(db.execute(
        select(TrustScore.user_id, TrustScore.score).where(TrustScore.user_id.in_(user_ids), TrustScore.category == "")
    ).all())
    for uid in set(user_ids) - set(have):
        have[uid] = refresh_trust(db, uid).score
    return have


def record_event(db: Session, user_id: int, kind: str, *, category: str | None = None,
                 request_id: int | None = None, value: float | None = None, counterparty_id: int | None = None) -> None:
    db.add(TrustEvent(user_id=user_id, kind=kind, category=category, request_id=request_id,
                      value=value, counterparty_id=counterparty_id))
    db.flush()


def category_trust_for(db: Session, user_id: int, category: str | None) -> float | None:
    if not category:
        return None
    return db.scalar(select(TrustScore.score).where(TrustScore.user_id == user_id, TrustScore.category == category))
