import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import bcrypt                                        # password hashing
import jwt                                           # PyJWT: create and verify tokens
from fastapi import Depends, HTTPException                # Depends = run first, HTTPException = error response
from fastapi.security import OAuth2PasswordBearer         # reads the token from the Authorization header
from sqlalchemy.orm import Session                        # type hint for the db session
from database import get_db                               # gives us a db session
from models import User                                   # to load the user from the users table

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")                 # the signing key from .env
if not SECRET_KEY:                                   # fail early, same idea as the Gemini key check
    raise RuntimeError("SECRET_KEY not found. Check your .env file.")

ALGORITHM = "HS256"                                  # the signing method
TOKEN_EXPIRE_MINUTES = 60                            # a token stops working after 1 hour


def hash_password(password: str) -> str:
    # bcrypt adds a random salt automatically; we store the result as text
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    # hashes the typed password the same way and compares it to the stored hash
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}   # sub = who the token is for, exp = when it dies
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)   # signs the payload with the secret
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")    # "tokens come from POST /login"; also adds the Authorize button in /docs


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    error = HTTPException(                                # one error used for every failure
        status_code=401,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])   # checks signature AND expiry
        user_id = int(payload["sub"])                     # pull the user id out of the token
    except (jwt.PyJWTError, KeyError, ValueError):        # bad signature, expired, missing or broken sub
        raise error
    user = db.query(User).filter(User.id == user_id).first()   # does this user still exist?
    if user is None:
        raise error
    return user                                           # routes receive this as current_user