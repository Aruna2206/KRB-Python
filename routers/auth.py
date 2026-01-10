# routers/auth.py
from fastapi import APIRouter, Form, Depends, HTTPException, status
from typing import Dict, Any

from models import *
from dependencies import *

router = APIRouter()

@router.post("/login", response_model=Dict[str, Any])
async def login_for_access_token(form_data: UserLogin):
    user = await db.users.find_one({"email": form_data.email})
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if form_data.role and user["role"] != form_data.role:
        raise HTTPException(status_code=401, detail="Invalid role")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["userId"], "role": user["role"]}, expires_delta=access_token_expires
    )
    refresh_token = create_refresh_token(data={"sub": user["userId"]})
    await db.users.update_one({"userId": user["userId"]}, {"$set": {"lastLogin": datetime.utcnow()}})
    return {
        "success": True,
        "message": "Login successful",
        "data": {
            "user": UserOut(**{k: v for k, v in user.items() if k != "password"}),
            "token": access_token,
            "refreshToken": refresh_token,
            "expiresIn": ACCESS_TOKEN_EXPIRE_MINUTES * 60
        }
    }

@router.post("/refresh", response_model=Dict[str, Any])
async def refresh_access_token(refresh_token_str: str = Form(...)):
    try:
        payload = jwt.decode(refresh_token_str, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None or payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        user = await db.users.find_one({"userId": user_id})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        access_token = create_access_token(data={"sub": user_id, "role": user["role"]})
        return {"success": True, "data": {"token": access_token, "expiresIn": ACCESS_TOKEN_EXPIRE_MINUTES * 60}}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@router.post("/logout", response_model=Dict[str, Any])
async def logout(_: UserOut = Depends(get_current_active_user)):
    return {"success": True, "message": "Logged out successfully"}

from utils_password import validate_password_policy

@router.post("/change-password", response_model=Dict[str, Any])
async def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    user: UserOut = Depends(get_current_active_user)
):
    stored_user = await db.users.find_one({"userId": user.userId})
    if not verify_password(current_password, stored_user["password"]):
        raise HTTPException(status_code=400, detail="Invalid current password")
    
    # Validate new password against policy
    await validate_password_policy(new_password)
    
    hashed_password = get_password_hash(new_password)
    await db.users.update_one({"userId": user.userId}, {"$set": {"password": hashed_password}})
    return {"success": True, "message": "Password changed successfully"}

@router.get("/me", response_model=Dict[str, Any])
async def get_current_user_profile(user: UserOut = Depends(get_current_active_user)):
    return {
        "success": True, 
        "data": {
            "user": user
        }
    }

@router.patch("/profile", response_model=Dict[str, Any])
async def update_user_profile(
    user_update: UserUpdate,
    user: UserOut = Depends(get_current_active_user)
):
    update_data = {k: v for k, v in user_update.dict(exclude_unset=True).items()}
    
    if not update_data:
        return {"success": True, "message": "No changes provided", "data": {"user": user}}

    # Check email uniqueness if changing email
    if "email" in update_data and update_data["email"] != user.email:
        existing_user = await db.users.find_one({"email": update_data["email"]})
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")

    await db.users.update_one(
        {"userId": user.userId},
        {"$set": {**update_data, "updatedAt": datetime.utcnow()}}
    )
    
    # Return updated user
    updated_user_doc = await db.users.find_one({"userId": user.userId})
    updated_user = UserOut(**{k: v for k, v in updated_user_doc.items() if k != "password"})
    
    return {
        "success": True,
        "message": "Profile updated successfully",
        "data": {"user": updated_user}
    }