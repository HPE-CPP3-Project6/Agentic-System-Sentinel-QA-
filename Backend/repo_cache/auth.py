"""
auth.py
-------
Authentication utilities for the Smart Task Manager.

Responsibilities:
    1. Password hashing & verification (bcrypt via passlib) – NFR8
    2. JWT creation & decoding (python-jose) – US-C15
    3. `get_current_user` FastAPI dependency – used on every protected endpoint

Security mechanisms (inline):
    - bcrypt: adaptive hash function with per-password salt; resistant to
      rainbow-table attacks and brute-force at scale.
    - JWT: tokens are signed with HS256.  Forged or expired tokens are
      rejected before any database access (US-C15/AC1, AC2).
    - `sub` claim stores the integer user ID (not email) to avoid leaking PII
      inside tokens that may be decoded client-side.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import User
from schemas import TokenData

# ---------------------------------------------------------------------------
# Password hashing context
# ---------------------------------------------------------------------------
# CryptContext auto-selects the strongest available bcrypt implementation and
# can transparently upgrade hashes if the work factor is increased later.
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",   # Automatically marks old schemes as deprecated
)

# ---------------------------------------------------------------------------
# OAuth2 token URL – points to the login endpoint
# ---------------------------------------------------------------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain_password: str) -> str:
    """
    Return the bcrypt hash of `plain_password`.

    The raw password is discarded by the caller immediately after this call;
    only the returned hash is persisted (NFR8).
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Constant-time comparison between `plain_password` and the stored hash.

    Returns True only if the password matches.  Using passlib's built-in
    comparison avoids timing-attack vulnerabilities in naive string equality.
    """
    return pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        data:          Payload claims.  Typically {"sub": str(user.id)}.
        expires_delta: Token lifetime; defaults to settings.ACCESS_TOKEN_EXPIRE_MINUTES.

    Returns:
        Encoded JWT string.

    Security:
        - Expiry (`exp`) is always set — tokens cannot live forever (FR5).
        - Signature uses the server-side SECRET_KEY; tampering invalidates it.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})

    # HS256 with a long secret key provides strong authenticity guarantees
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode_token(token: str) -> TokenData:
    """
    Decode and validate a JWT, returning the embedded TokenData.

    Raises:
        HTTPException 401 – if the token is missing, malformed, expired, or
        the `sub` claim is absent.
    """
    credential_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        sub: str = payload.get("sub")
        if sub is None:
            # Token is malformed — reject immediately (US-C15/AC2)
            raise credential_exception
        return TokenData(user_id=int(sub))
    except JWTError:
        # Covers: expired signature, invalid signature, malformed token
        raise credential_exception


# ---------------------------------------------------------------------------
# FastAPI dependency: get_current_user
# ---------------------------------------------------------------------------

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency injected into every protected endpoint.

    Workflow:
        1. Extract the Bearer token from the Authorization header.
        2. Decode and validate the JWT signature + expiry.
        3. Extract `user_id` from the `sub` claim.
        4. Look up the user in the database to confirm the account still exists.
        5. Return the ORM User object.

    Raises:
        HTTPException 401 – on any authentication failure (US-C15/AC1, AC2).

    Usage:
        @router.get("/protected")
        def protected_route(current_user: User = Depends(get_current_user)):
            ...
    """
    token_data = _decode_token(token)

    # Database lookup ensures the user account was not deleted after token issuance
    user: Optional[User] = db.query(User).filter(User.id == token_data.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ---------------------------------------------------------------------------
# Helper: authenticate user credentials
# ---------------------------------------------------------------------------

def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """
    Look up a user by email and verify their password.

    Returns the User ORM object on success, or None on failure.
    Callers must treat a None return as an authentication failure and MUST NOT
    reveal whether the email exists (prevents user enumeration attacks).
    """
    user: Optional[User] = db.query(User).filter(User.email == email).first()
    if user is None:
        # Run a dummy hash to prevent timing-based user enumeration
        pwd_context.dummy_verify()
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
