# dependencies.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
import os
from typing import Optional

from config import db  # Import db from config (fixes circular import)
from models import *

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UserOut:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
        user = await db.users.find_one({"userId": user_id})
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return UserOut(**{k: v for k, v in user.items() if k != "password"})
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")

async def get_current_active_user(current_user: UserOut = Depends(get_current_user)) -> UserOut:
    if current_user.status != Status.ACTIVE:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

def require_role(required_role: Role):
    def role_checker(current_user: UserOut = Depends(get_current_active_user)):
        if current_user.role != required_role and current_user.role != Role.ADMIN:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return role_checker

def verify_password(plain_password, hashed_password):
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        # Fallback for plain text passwords
        print(f"Password verification error: {e}")
        return plain_password == hashed_password

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict):
    to_encode = data.copy()
    to_encode.update({"type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def generate_id(prefix: str) -> str:
    from datetime import datetime
    from uuid import uuid4
    timestamp = datetime.utcnow().strftime("%Y%m%d")
    unique = str(uuid4()).split('-')[0].upper()
    return f"{prefix}{timestamp}{unique}"

async def get_object_or_404(collection, id_field: str, id_value: str, model_class):
    from bson.errors import InvalidId
    try:
        obj = await collection.find_one({id_field: id_value})
        if not obj:
            raise HTTPException(status_code=404, detail="Object not found")
        obj["id"] = str(obj.get("_id", ""))
        del obj["_id"]  # Clean up for Pydantic
        return model_class(**obj)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid ID format")