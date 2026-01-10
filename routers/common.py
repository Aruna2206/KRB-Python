# routers/common.py
from fastapi import APIRouter, Depends, Query, Form, File, UploadFile, HTTPException
from typing import List, Dict, Any

from models import *
from dependencies import *

common_user = get_current_active_user

router = APIRouter()

@router.get("/notifications", response_model=Dict[str, Any])  # Extend with unreadCount
async def get_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=100),
    unread_only: bool = Query(False),
    current_user: UserOut = Depends(common_user)
):
    query = {"userId": current_user.userId}
    if unread_only:
        query["isRead"] = False
    skip = (page - 1) * limit
    cursor = db.notifications.find(query).sort("createdAt", -1).skip(skip).limit(limit)
    notifs = [Notification(**{**doc, "id": str(doc["_id"])}) async for doc in cursor]
    total = await db.notifications.count_documents(query)
    unread_count = await db.notifications.count_documents({**query, "isRead": False})
    pagination = {
        "currentPage": page,
        "totalPages": (total + limit - 1) // limit,
        "totalRecords": total,
        "limit": limit
    }
    return {
        "success": True,
        "data": PaginatedResponse(data=notifs, pagination=pagination).dict(),
        "unreadCount": unread_count
    }

@router.patch("/notifications/{notification_id}/read", response_model=Dict[str, Any])
async def mark_notification_read(notification_id: str, current_user: UserOut = Depends(common_user)):
    result = await db.notifications.update_one(
        {"notificationId": notification_id, "userId": current_user.userId},
        {"$set": {"isRead": True, "readAt": datetime.utcnow()}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True, "message": "Notification marked as read"}

@router.get("/pricing", response_model=Dict[str, Any])
async def get_pricing_info():
    pricings = [Pricing(**{**doc, "id": str(doc["_id"])}) async for doc in db.pricing.find({"status": Status.ACTIVE}).sort("effectiveFrom", -1)]
    return {"success": True, "data": {"pricing": pricings}}

@router.post("/upload/image")
async def upload_image(
    file: UploadFile = File(...),
    type_: str = Form(...),
    current_user: UserOut = Depends(common_user)
):
    contents = await file.read()
    import hashlib
    filename = f"{current_user.userId}_{type_}_{hashlib.md5(contents).hexdigest()}.{file.filename.split('.')[-1]}"
    url = f"https://storage.example.com/images/{filename}"
    size = len(contents)
    return {
        "success": True,
        "message": "Image uploaded successfully",
        "data": {"url": url, "filename": filename, "size": size}
    }

@router.get("/users/by-role", response_model=Dict[str, Any])
async def get_users_by_role(
    role: Role, 
    current_user: UserOut = Depends(common_user)
):
    users_list = []
    cursor = db.users.find({"role": role, "status": Status.ACTIVE})
    
    async for doc in cursor:
        user = UserOut(**{**doc, "id": str(doc["_id"])})
        if role == Role.COLLECTION_TEAM:
             # Count assigned FBOs
            count = await db.fbos.count_documents({"assignedCollectors": user.userId})
            if user.metadata is None:
                user.metadata = {}
            user.metadata["assignmentCount"] = count
        users_list.append(user)
        
    return {"success": True, "data": users_list}

@router.get("/settings/contact", response_model=Dict[str, Any])
async def get_contact_settings():
    keys = ["supportEmail", "supportPhone", "supportAddress"]
    cursor = db.settings.find({"settingKey": {"$in": keys}})
    settings = {doc["settingKey"]: doc["settingValue"] async for doc in cursor}
    
    return {
        "success": True, 
        "data": {
            "email": settings.get("supportEmail", "support@krbcleanenergy.com"),
            "phone": settings.get("supportPhone", "+91 1800 123 4567"),
            "address": settings.get("supportAddress", "Bangalore, Karnataka")
        }
    }