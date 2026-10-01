"""Neighbourhood marketplace: items for sale, free gifts shared with neighbours, and local services/amenities."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Listing, ListingClaim, ListingKind, ListingStatus, User
from ..schemas import ClaimIn, ListingIn, ListingUpdate
from ..security import current_user
from ..services.geo import bbox, fuzz, haversine_km
from ..services.realtime import notify

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])

CATEGORIES = {
    "sell": ["furniture", "electronics", "appliances", "books", "clothing", "kids", "sports", "other"],
    "gift": ["furniture", "electronics", "appliances", "books", "clothing", "kids", "food", "plants", "other"],
    "service": ["pest_control", "plumbing", "electrical", "cleaning", "carpentry", "ac_repair", "painting", "tutoring", "other"],
}


def _first(name: str) -> str:
    return (name or "Neighbour").split()[0]


def _out(l: Listing, viewer: User, lat: float | None, lng: float | None, claim: ListingClaim | None = None) -> dict:
    dist = haversine_km(lat, lng, l.lat, l.lng) if (lat is not None and l.lat is not None) else None
    mine = l.owner_id == viewer.id
    return {
        "id": l.id, "kind": l.kind, "category": l.category, "title": l.title, "description": l.description,
        "price": l.price, "condition": l.condition, "status": l.status, "created_at": l.created_at.isoformat(),
        "distance_km": round(dist, 1) if dist is not None else None,
        "owner": {"id": l.owner_id, "name": l.owner.name if mine else _first(l.owner.name), "verified": l.owner.identity_verified},
        "is_mine": mine,
        # a business phone is meant to be public; a private seller's number never is
        "contact_phone": l.contact_phone if l.kind == ListingKind.SERVICE else None,
        "my_claim": {"id": claim.id, "status": claim.status} if claim else None,
        "reserved_for_me": l.reserved_for_id == viewer.id,
        "claim_count": sum(1 for c in l.claims if c.status == "pending") if mine else None,
    }


def _claims_by_listing(db: Session, user: User, ids: list[int]) -> dict[int, ListingClaim]:
    if not ids:
        return {}
    return {c.listing_id: c for c in db.scalars(select(ListingClaim).where(ListingClaim.user_id == user.id, ListingClaim.listing_id.in_(ids)))}


@router.get("/categories")
def categories(user: User = Depends(current_user)):
    return CATEGORIES


@router.get("")
def browse(kind: str | None = None, category: str | None = None, q: str | None = Query(None, max_length=80),
           max_price: float | None = Query(None, ge=0), lat: float | None = Query(None, ge=-90, le=90),
           lng: float | None = Query(None, ge=-180, le=180), radius_km: float = Query(10, gt=0, le=100),
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    if kind and kind not in ListingKind.ALL:
        raise HTTPException(422, "Unknown listing kind")
    lat = lat if lat is not None else user.lat
    lng = lng if lng is not None else user.lng
    query = select(Listing).where(Listing.status.in_(ListingStatus.ACTIVE))
    if kind:
        query = query.where(Listing.kind == kind)
    if category:
        query = query.where(Listing.category == category)
    if q:
        like = f"%{q}%"
        query = query.where(or_(Listing.title.ilike(like), Listing.description.ilike(like)))
    if max_price is not None:
        query = query.where(or_(Listing.price.is_(None), Listing.price <= max_price))
    if lat is not None and lng is not None:
        a, b, c, d = bbox(lat, lng, radius_km)
        query = query.where(Listing.lat.between(a, b), Listing.lng.between(c, d))
    rows = db.scalars(query.order_by(Listing.created_at.desc()).limit(300)).all()
    claims = _claims_by_listing(db, user, [r.id for r in rows])
    out = [_out(r, user, lat, lng, claims.get(r.id)) for r in rows]
    out = [o for o in out if o["distance_km"] is None or o["distance_km"] <= radius_km]
    return sorted(out, key=lambda o: (o["distance_km"] if o["distance_km"] is not None else 1e9))


@router.get("/mine")
def mine(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Listings I posted, plus the gifts/items I've asked for."""
    posted = db.scalars(select(Listing).where(Listing.owner_id == user.id).order_by(Listing.created_at.desc()).limit(200)).all()
    asked = list(db.scalars(select(ListingClaim).where(ListingClaim.user_id == user.id).order_by(ListingClaim.id.desc()).limit(200)))
    asked_listings = {l.id: l for l in db.scalars(select(Listing).where(Listing.id.in_([c.listing_id for c in asked])))} if asked else {}
    return {
        "posted": [_out(l, user, user.lat, user.lng) for l in posted],
        "requested": [_out(asked_listings[c.listing_id], user, user.lat, user.lng, c) for c in asked if c.listing_id in asked_listings],
    }


@router.post("", status_code=201)
def create(body: ListingIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.category not in CATEGORIES[body.kind]:
        raise HTTPException(422, "Pick a category from the list for this type of listing")
    if user.lat is None:
        raise HTTPException(422, "Set your location first so neighbours nearby can find your listing")
    if body.kind == ListingKind.SELL and not body.price:
        raise HTTPException(422, "Add a price for items you're selling (or post it as a free gift)")
    if body.kind == ListingKind.SERVICE and not body.contact_phone:
        raise HTTPException(422, "Add a contact number so people can book your service")
    if body.kind == ListingKind.GIFT and body.price:
        raise HTTPException(422, "Gifts are free. Remove the price or post it for sale")
    lat, lng = fuzz(user.lat, user.lng, 3)  # ~100 m: close enough to rank by distance, never a home address
    l = Listing(owner_id=user.id, kind=body.kind, category=body.category, title=body.title, description=body.description,
                price=body.price, condition=body.condition if body.kind != ListingKind.SERVICE else None,
                contact_phone=body.contact_phone if body.kind == ListingKind.SERVICE else None, lat=lat, lng=lng)
    db.add(l)
    db.commit()
    db.refresh(l)
    return _out(l, user, user.lat, user.lng)


def _get(db: Session, listing_id: int) -> Listing:
    l = db.get(Listing, listing_id)
    if not l:
        raise HTTPException(404, "Listing not found")
    return l


@router.get("/{listing_id}")
def detail(listing_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    l = _get(db, listing_id)
    claim = db.scalar(select(ListingClaim).where(ListingClaim.listing_id == l.id, ListingClaim.user_id == user.id))
    out = _out(l, user, user.lat, user.lng, claim)
    if l.owner_id == user.id:
        out["claims"] = [{"id": c.id, "user": {"id": c.user_id, "name": _first(c.user.name), "verified": c.user.identity_verified},
                          "message": c.message, "status": c.status, "created_at": c.created_at.isoformat()} for c in l.claims]
    return out


@router.patch("/{listing_id}")
def update(listing_id: int, body: ListingUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    l = _get(db, listing_id)
    if l.owner_id != user.id:
        raise HTTPException(403, "Only the person who posted this can change it")
    data = body.model_dump(exclude_unset=True)
    if data.get("price") is not None and l.kind == ListingKind.GIFT:
        raise HTTPException(422, "Gifts are free")
    for k, v in data.items():
        if v is not None:
            setattr(l, k, v)
    if l.status == ListingStatus.AVAILABLE:
        l.reserved_for_id = None
    db.commit()
    return _out(l, user, user.lat, user.lng)


@router.delete("/{listing_id}", status_code=204)
def remove(listing_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    l = _get(db, listing_id)
    if l.owner_id != user.id and user.role != "admin":
        raise HTTPException(403, "Only the person who posted this can remove it")
    db.delete(l)
    db.commit()


@router.post("/{listing_id}/claims", status_code=201)
def claim(listing_id: int, body: ClaimIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """'I'd like this' on a gift/item, or an enquiry on a service. Tells the owner; the owner picks who gets it."""
    l = _get(db, listing_id)
    if l.owner_id == user.id:
        raise HTTPException(400, "This is your own listing")
    if l.status != ListingStatus.AVAILABLE:
        raise HTTPException(409, "This listing is no longer available")
    existing = db.scalar(select(ListingClaim).where(ListingClaim.listing_id == l.id, ListingClaim.user_id == user.id))
    if existing and existing.status != "withdrawn":
        raise HTTPException(409, "You've already asked about this")
    c = existing or ListingClaim(listing_id=l.id, user_id=user.id)
    c.message, c.status = body.message, "pending"
    db.add(c)
    verb = {"gift": "wants your gift", "sell": "is interested in", "service": "enquired about"}[l.kind]
    notify(db, l.owner_id, "marketplace_claim", f"{_first(user.name)} {verb}: {l.title}", body.message, {"listing_id": l.id})
    db.commit()
    return {"id": c.id, "status": c.status}


@router.post("/{listing_id}/claims/{claim_id}/withdraw")
def withdraw(listing_id: int, claim_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(ListingClaim, claim_id)
    if not c or c.listing_id != listing_id or c.user_id != user.id:
        raise HTTPException(404, "Request not found")
    l = _get(db, listing_id)
    if l.reserved_for_id == user.id:
        l.status, l.reserved_for_id = ListingStatus.AVAILABLE, None
    c.status = "withdrawn"
    db.commit()
    return {"status": c.status}


@router.post("/{listing_id}/claims/{claim_id}/{decision}")
def decide(listing_id: int, claim_id: int, decision: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if decision not in ("accept", "decline"):
        raise HTTPException(404, "Not found")
    l = _get(db, listing_id)
    if l.owner_id != user.id:
        raise HTTPException(403, "Only the person who posted this can decide")
    c = db.get(ListingClaim, claim_id)
    if not c or c.listing_id != l.id:
        raise HTTPException(404, "Request not found")
    if c.status != "pending":
        raise HTTPException(409, "Already decided")
    if decision == "accept":
        if l.status != ListingStatus.AVAILABLE:
            raise HTTPException(409, "You've already promised this to someone")
        c.status = "accepted"
        if l.kind != ListingKind.SERVICE:
            l.status, l.reserved_for_id = ListingStatus.RESERVED, c.user_id
        body = "They'll be in touch." if l.kind == ListingKind.SERVICE else "Arrange pickup with them in person or by phone."
        notify(db, c.user_id, "marketplace_accepted", f"{_first(user.name)} said yes: {l.title}", body, {"listing_id": l.id})
    else:
        c.status = "declined"
        notify(db, c.user_id, "marketplace_declined", f"Not this time: {l.title}", "The owner chose someone else or it's no longer available.", {"listing_id": l.id})
    db.commit()
    return {"status": c.status}
