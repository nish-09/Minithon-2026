import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import serializers as ser
from ..db import get_db
from ..models import Profile, RelationshipPreference, RevokedToken, User
from ..schemas import LoginIn, RegisterIn
from ..security import bearer, create_token, current_user, decode_token, hash_password, verify_password
from ..services import credits as credits_svc

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Simple in-process brute-force throttle: 8 failures / 5 min per (ip, email). Use a shared store
# (Redis) when running more than one API process.
_FAILS: dict[str, deque] = defaultdict(deque)
WINDOW_S, MAX_FAILS = 300, 8
_DUMMY_HASH = hash_password("not-a-real-password")  # constant-time-ish path for unknown emails


def _throttled(key: str) -> bool:
    q = _FAILS[key]
    now = time.monotonic()
    while q and now - q[0] > WINDOW_S:
        q.popleft()
    return len(q) >= MAX_FAILS


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    if body.phone and db.scalar(select(User.id).where(User.phone == body.phone)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this phone number already exists")
    user = User(name=body.name, email=email, phone=body.phone, password_hash=hash_password(body.password))
    user.profile = Profile()
    db.add(user)
    try:
        db.flush()
        db.add(RelationshipPreference(user_id=user.id))
        credits_svc.ensure_account(db, user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Account already exists")
    return {"token": create_token(user.id), "user": ser.user_me(db, user)}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    key = f"{request.client.host if request.client else '?'}|{email}"
    if _throttled(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again in a few minutes.")
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not (user and ok and user.is_active):
        _FAILS[key].append(time.monotonic())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    _FAILS.pop(key, None)
    return {"token": create_token(user.id), "user": ser.user_me(db, user)}


@router.post("/logout", status_code=204)
def logout(creds: HTTPAuthorizationCredentials = Depends(bearer), user: User = Depends(current_user), db: Session = Depends(get_db)):
    payload = decode_token(creds.credentials)
    if payload and db.get(RevokedToken, payload["jti"]) is None:
        db.add(RevokedToken(jti=payload["jti"], expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc)))
        db.commit()


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.commit()  # persists last_seen_at
    return ser.user_me(db, user)
