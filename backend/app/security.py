import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import RevokedToken, Role, User, utcnow

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.jwt_expire_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp, "jti": uuid.uuid4().hex}, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
        int(payload["sub"])
        return payload
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def user_from_token(db: Session, token: str) -> User | None:
    payload = decode_token(token)
    if payload is None or db.get(RevokedToken, payload.get("jti", "")) is not None:
        return None
    user = db.get(User, int(payload["sub"]))
    return user if user and user.is_active else None


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = user_from_token(db, creds.credentials)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user.last_seen_at = utcnow()
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user
