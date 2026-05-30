"""
routers/auth_router.py
----------------------
Authentication endpoints:
    POST /register  – Create a new user account
    POST /login     – Exchange credentials for a JWT access token
    POST /logout    – Inform the client to discard its token (FR3)

Security notes:
    - Passwords are hashed before any DB write (NFR8).
    - Login errors use a generic message to prevent user enumeration.
    - The logout endpoint is stateless (tokens are short-lived; production
      deployments may add a server-side blocklist / Redis TTL cache).
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import authenticate_user, create_access_token, hash_password
from config import settings
from database import get_db
from models import User
from schemas import Token, UserCreate, UserOut

router = APIRouter(tags=["Authentication"])


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------
@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
    description=(
        "Creates a new user with a unique email address. "
        "The password is hashed with bcrypt before storage (NFR8). "
        "Returns the newly created user (without the password hash)."
    ),
)
def register(user_in: UserCreate, db: Session = Depends(get_db)) -> User:
    """
    FR1: Register using email and password.

    Steps:
        1. Hash the supplied password with bcrypt — raw value is never persisted.
        2. Insert the new User row inside a transaction.
        3. On duplicate email, return 409 Conflict (not 500).
    """
    # SECURITY (NFR8): hash immediately; the plain-text password is discarded
    hashed_pw = hash_password(user_in.password)

    new_user = User(email=user_in.email, hashed_password=hashed_pw)
    db.add(new_user)
    try:
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )
    return new_user


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------
@router.post(
    "/login",
    response_model=Token,
    summary="Obtain a JWT access token",
    description=(
        "Accepts OAuth2 password-grant credentials and returns a signed JWT. "
        "The token must be included in the Authorization header as "
        "`Bearer <token>` for all protected endpoints (US-C15)."
    ),
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """
    FR2: Log in using valid credentials.

    Steps:
        1. Look up the user by email; verify the bcrypt hash.
        2. On failure, return a generic 401 — do NOT reveal whether the email
           exists (prevents user enumeration).
        3. On success, issue a signed JWT with an expiry (FR5).
    """
    user = authenticate_user(db, email=form_data.username, password=form_data.password)
    if not user:
        # Generic error message prevents user enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=access_token, token_type="bearer")


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------
@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Log out the current user",
    description=(
        "Stateless logout: instructs the client to discard its token (FR3). "
        "For production, complement with a server-side token blocklist."
    ),
)
def logout() -> dict:
    """
    FR3: Log out the current session.

    JWT tokens are stateless; the server cannot invalidate them unilaterally
    without a blocklist.  The client MUST discard the token on logout.
    """
    return {"detail": "Successfully logged out. Please discard your access token."}
