import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

ITER = 200_000
bearer = HTTPBearer(auto_error=False)

EXEC, COFOUNDER = "finance_exec", "cofounder"


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER)
    return f"pbkdf2${ITER}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), dk)
    except Exception:
        return False


def make_token(email: str, role: str, name: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_hours)
    return jwt.encode({"sub": email, "role": role, "name": name, "exp": exp}, settings.jwt_secret, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not cred:
        raise HTTPException(401, "Not signed in")
    try:
        p = jwt.decode(cred.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired, please sign in again")
    return {"email": p["sub"], "role": p["role"], "name": p.get("name", "")}


def require_exec(user: dict = Depends(current_user)) -> dict:
    """Write actions (upload, mapping, rate cards, claim status, re-run) are for finance executives."""
    if user["role"] != EXEC:
        raise HTTPException(403, "Only a finance executive can do this")
    return user


def require_cofounder(user: dict = Depends(current_user)) -> dict:
    if user["role"] != COFOUNDER:
        raise HTTPException(403, "Only the co-founder can do this")
    return user
