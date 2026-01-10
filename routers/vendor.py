# routers/vendor.py
from fastapi import APIRouter, Depends, Query, Form, HTTPException
from typing import Dict, Any
import os


from models import *
from dependencies import *

vendor_user = require_role(Role.FBO)

router = APIRouter()

def serialize_doc(doc):
    if not doc:
        return None
    if "_id" in doc:
        doc["id"] = str(doc["_id"])
        doc.pop("_id")
    # Recursively handle nested ObjectIds if any (though usually not needed for these models)
    return doc

async def get_fbo_for_user(current_user: UserOut):
    # Try exact match first
    fbo = await db.fbos.find_one({"contactPerson.email": current_user.email})
    if not fbo:
        # Try case-insensitive
        fbo = await db.fbos.find_one({"contactPerson.email": {"$regex": f"^{current_user.email}$", "$options": "i"}})
    
    # Fallback for Admins to allow them to preview vendor pages
    if not fbo and current_user.role == Role.ADMIN:
        fbo = await db.fbos.find_one({"status": Status.ACTIVE})
        if not fbo:
            fbo = await db.fbos.find_one({}) # Any FBO
            
    if not fbo:
        raise HTTPException(
            status_code=404, 
            detail=f"FBO Profile not found for {current_user.email}. Please ensure an FBO profile is linked to this email."
        )
    return fbo

@router.get("/dashboard/stats", response_model=Dict[str, Any])
async def vendor_dashboard(
    current_user: UserOut = Depends(vendor_user),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None)
):
    try:
        fbo = await get_fbo_for_user(current_user)
    except HTTPException as e:
        if e.status_code == 404:
            return {
                "success": True, 
                "data": {
                    "totalCollections": 0,
                    "totalVolume": 0,
                    "totalEarnings": 0,
                    "pendingAmount": 0,
                    "businessName": current_user.name or "Your Business",
                    "recentCollections": [],
                    "nextPickup": None, 
                    "paymentDistribution": [{"name": "No Data", "value": 1}],
                    "qualityScore": "N/A",
                    "consistency": 0,
                    "isUnlinked": True
                }
            }
        raise e
    
    # Real Stats
    fbo_id = fbo["fboId"]
    
    # Base match query
    match_query = {"fboId": fbo_id}
    
    # Apply date filters if provided
    if start_date:
        if "collectionDate" not in match_query: match_query["collectionDate"] = {}
        match_query["collectionDate"]["$gte"] = start_date
        
    if end_date:
        if "collectionDate" not in match_query: match_query["collectionDate"] = {}
        match_query["collectionDate"]["$lte"] = end_date
        
    total_collections = await db.collections.count_documents(match_query)
    
    # Aggregate total volume
    volume_cursor = db.collections.aggregate([
        {"$match": match_query},
        {"$group": {"_id": None, "total": {"$sum": "$quantityCollected"}}}
    ])
    volume_result = await volume_cursor.to_list(1)
    
    # Aggregate earnings (Bills)
    # Aggregate earnings (Total Value of Collections)
    earnings_cursor = db.collections.aggregate([
        {"$match": match_query},
        {"$group": {"_id": None, "total": {"$sum": "$totalAmount"}}}
    ])
    earnings_result = await earnings_cursor.to_list(1)

    # Aggregate pending balance (Collections not yet paid) 
    pending_match = match_query.copy()
    pending_match["status"] = {"$ne": "paid"}
    
    balance_cursor = db.collections.aggregate([
        {"$match": pending_match},
        {"$group": {"_id": None, "total": {"$sum": "$totalAmount"}}}
    ])
    balance_result = await balance_cursor.to_list(1)

    # Recent Collections (Limit 5)
    recent_collections = []
    recent_cursor = db.collections.find(match_query).sort("collectionDate", -1).limit(5)
    async for c in recent_cursor:
        recent_collections.append({
            "id": c.get("collectionId"),
            "date": c.get("collectionDate"),
            "volume": c.get("quantityCollected"),
            "amount": c.get("totalAmount"),
            "status": c.get("status")
        })

    # Next Pickup (Logic: Latest pending request or None)
    # Finding latest open request for this FBO or user
    next_pickup = None
    # Assuming we have a requests collection or using notifications for now. 
    # For this implementation, we'll check if there is any scheduled trip for this FBO in the future.
    # Since we don't have a direct 'trips' collection easily accessible here without more queries, 
    # we can try to find a 'scheduled' collection or use a heuristic.
    # Let's check for a "scheduled" status collection in the future (unlikely for collection history)
    # OR check notifications/requests. Let's use a placeholder heuristic looking for 'pending' requests if visible, 
    # or just NULL if no explicit schedule exists.
    # Improved: Check if there is a 'processing' or 'scheduled' collection entry with future date? 
    # Usually collections are created upon pickup.
    # Let's check the notifications for "TRIP_ASSIGNED" for this FBO in future?
    # Simple Fallback:
    next_pickup = None 

    # Payment Distribution (Based on Collections)
    payment_status_cursor = db.collections.aggregate([
        {"$match": match_query},
        {"$group": {"_id": "$status", "count": {"$sum": 1}, "value": {"$sum": "$totalAmount"}}}
    ])
    payment_dist_map = {}
    async for doc in payment_status_cursor:
        payment_dist_map[doc["_id"]] = doc["value"]
    
    # Map to frontend expected format
    # Quality Score & Consistency
    quality_cursor = db.collections.aggregate([
        {"$match": match_query},
        {"$group": {"_id": "$qualityGrade", "count": {"$sum": 1}}}
    ])
    quality_counts = {}
    total_quality_count = 0
    async for doc in quality_cursor:
        if doc["_id"]:
            quality_counts[doc["_id"]] = doc["count"]
            total_quality_count += doc["count"]
            
    quality_score = "N/A"
    consistency = 0
    
    if total_quality_count > 0:
        # Find mode
        most_frequent_grade = max(quality_counts, key=quality_counts.get)
        count_of_mode = quality_counts[most_frequent_grade]
        consistency = int((count_of_mode / total_quality_count) * 100)
        
        # Map Grade to Display Text
        grade_map = {
            "A": "Excellent",
            "B": "Good",
            "C": "Fair",
            "Rejected": "Poor"
        }
        quality_score = grade_map.get(most_frequent_grade, most_frequent_grade)
    
    # Map to frontend expected format
    payment_distribution = [
        {"name": "Paid", "value": payment_dist_map.get("paid", 0)},
        {"name": "Processing", "value": payment_dist_map.get("approved", 0)},
        {"name": "Pending", "value": payment_dist_map.get("pending", 0)}
    ]
    # Filter out zero values if desired, or keep structure
    payment_distribution = [p for p in payment_distribution if p["value"] > 0]
    if not payment_distribution:
        payment_distribution = [{"name": "No Data", "value": 1}]

    data = {
        "totalCollections": total_collections,
        "totalVolume": volume_result[0]["total"] if volume_result else 0,
        "totalEarnings": earnings_result[0]["total"] if earnings_result else 0,
        "pendingAmount": balance_result[0]["total"] if balance_result else 0,
        "businessName": fbo.get("businessName", "Your Business"),
        "recentCollections": recent_collections,
        "nextPickup": next_pickup, 
        "paymentDistribution": payment_distribution,
        "qualityScore": quality_score,
        "consistency": consistency
    }
    return {"success": True, "data": data}

@router.get("/bills", response_model=Dict[str, Any])
async def get_vendor_bills(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=100),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: UserOut = Depends(vendor_user)
):
    try:
        fbo = await get_fbo_for_user(current_user)
    except HTTPException as e:
        if e.status_code == 404:
            return {
                "success": True,
                "data": {
                    "bills": [],
                    "total": 0,
                    "page": page,
                    "totalPages": 0
                }
            }
        raise e
    
    query = {"fboId": fbo["fboId"]}
    if start_date:
        if "billDate" not in query: query["billDate"] = {}
        query["billDate"]["$gte"] = start_date
    if end_date:
        if "billDate" not in query: query["billDate"] = {}
        query["billDate"]["$lte"] = end_date
        
    skip = (page - 1) * limit
    cursor = db.bills.find(query).sort("billDate", -1).skip(skip).limit(limit)
    bills = [serialize_doc(doc) async for doc in cursor]
    total = await db.bills.count_documents(query)
    
    return {
        "success": True,
        "data": {
            "bills": bills,
            "total": total,
            "page": page,
            "totalPages": (total + limit - 1) // limit
        }
    }

@router.get("/collections", response_model=PaginatedResponse[Collection])
async def get_vendor_collections(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=100),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: UserOut = Depends(vendor_user)
):
    try:
        fbo = await get_fbo_for_user(current_user)
    except HTTPException as e:
        if e.status_code == 404:
            return PaginatedResponse(
                data=[], 
                pagination={
                    "currentPage": page,
                    "totalPages": 0,
                    "totalRecords": 0,
                    "limit": limit
                }
            )
        raise e
    
    query = {"fboId": fbo["fboId"]}
    if start_date:
        if "collectionDate" not in query: query["collectionDate"] = {}
        query["collectionDate"]["$gte"] = start_date
    if end_date:
        if "collectionDate" not in query: query["collectionDate"] = {}
        query["collectionDate"]["$lte"] = end_date
    skip = (page - 1) * limit
    cursor = db.collections.find(query).sort("collectionDate", -1).skip(skip).limit(limit)
    collections = [Collection(**serialize_doc(doc)) async for doc in cursor]
    total = await db.collections.count_documents(query)
    pagination = {
        "currentPage": page,
        "totalPages": (total + limit - 1) // limit,
        "totalRecords": total,
        "limit": limit
    }
    return PaginatedResponse(data=collections, pagination=pagination)

@router.get("/payments", response_model=Dict[str, Any])
async def get_vendor_payments(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=100),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: UserOut = Depends(vendor_user)
):
    try:
        fbo = await get_fbo_for_user(current_user)
    except HTTPException as e:
        if e.status_code == 404:
            return {
                "data": [],
                "pagination": {
                    "currentPage": page,
                    "totalPages": 0,
                    "totalRecords": 0,
                    "limit": limit
                }
            }
        raise e
    
    # Fetch all collections with payment history for this FBO
    query = {
        "fboId": fbo["fboId"],
        "status": "paid",  # Only fetch paid collections
        "paymentDetails.history": {"$exists": True, "$ne": []}
    }
    
    # Get all collections that have payment history
    cursor = db.collections.find(query).sort("paymentDetails.paymentDate", -1)
    collections = [serialize_doc(doc) async for doc in cursor]
    
    # Extract all payment transactions from collections
    all_payments = []
    for coll in collections:
        payment_details = coll.get("paymentDetails", {})
        history = payment_details.get("history", [])
        
        for payment_txn in history:
            all_payments.append({
                "paymentId": payment_txn.get("transactionId", ""),
                "paymentDate": payment_txn.get("date"),
                "amountPaid": payment_txn.get("amount", 0),
                "paymentMethod": payment_txn.get("method", ""),
                "transactionReference": payment_txn.get("reference", ""),
                "status": "completed",  # Payment history items are always completed
                "collectionId": coll.get("collectionId"),
                "totalAmount": coll.get("totalAmount", 0),
                "netAmount": payment_txn.get("amount", 0),
                "fboId": fbo["fboId"],
                "fboName": coll.get("fboName", "")
            })
    
    # Filter by date if provided (in-memory filtering since it's an aggregated list)
    if start_date:
        # DB dates are likely naive UTC (datetime.utcnow), so make input naive for comparison
        start_naive = start_date.replace(tzinfo=None)
        all_payments = [p for p in all_payments if p.get("paymentDate") and p["paymentDate"] >= start_naive]
    if end_date:
        end_naive = end_date.replace(tzinfo=None)
        all_payments = [p for p in all_payments if p.get("paymentDate") and p["paymentDate"] <= end_naive]

    # Sort by date descending
    all_payments.sort(key=lambda x: x.get("paymentDate", datetime.min), reverse=True)
    
    # Apply pagination
    total = len(all_payments)
    skip = (page - 1) * limit
    paginated_payments = all_payments[skip:skip + limit]
    
    pagination = {
        "currentPage": page,
        "totalPages": (total + limit - 1) // limit if total > 0 else 0,
        "totalRecords": total,
        "limit": limit
    }
    
    return {
        "data": paginated_payments,
        "pagination": pagination
    }

@router.get("/profile", response_model=FBO)
async def get_vendor_profile(current_user: UserOut = Depends(vendor_user)):
    fbo = await get_fbo_for_user(current_user)
    return FBO(**serialize_doc(fbo))

@router.put("/profile", response_model=Dict[str, Any])
async def update_vendor_profile(
    profile_update: Dict[str, Any],
    current_user: UserOut = Depends(vendor_user)
):
    # Try exact match first, then case-insensitive
    fbo = await db.fbos.find_one({"contactPerson.email": current_user.email})
    if not fbo:
        # Try case-insensitive match
        fbo = await db.fbos.find_one({"contactPerson.email": {"$regex":f"^{current_user.email}$", "$options": "i"}})
    
    if not fbo:
        raise HTTPException(status_code=404, detail="Profile not found - Please ensure your FBO profile is linked to your email")
    await db.fbos.update_one({"fboId": fbo["fboId"]}, {"$set": {**profile_update, "updatedAt": datetime.utcnow()}})
    return {"success": True, "message": "Profile updated successfully", "data": {"fboId": fbo["fboId"], "updatedAt": datetime.utcnow()}}

@router.post("/request-collection", response_model=Dict[str, Any])
async def request_collection(
    estimated_quantity: float = Form(...),
    preferred_date: str = Form(...),
    notes: Optional[str] = Form(None),
    current_user: UserOut = Depends(vendor_user)
):
    # Try exact match first, then case-insensitive
    fbo = await db.fbos.find_one({"contactPerson.email": current_user.email})
    if not fbo:
        # Try case-insensitive match
        fbo = await db.fbos.find_one({"contactPerson.email": {"$regex":f"^{current_user.email}$", "$options": "i"}})
    
    if fbo:
        fbo_id = fbo["fboId"]
        business_name = fbo["businessName"]
    else:
        # Fallback if profile not linked
        fbo_id = "UNLINKED"
        business_name = current_user.name or current_user.email
        
    request_id = generate_id("REQ")
    
    # 1. Simplify: Find ANY active admin to notify (or broadcast in future)
    admin_user = await db.users.find_one({"role": Role.ADMIN, "status": Status.ACTIVE})
    admin_id = admin_user["userId"] if admin_user else "ADMIN_ID"
    
    # Notify Admin
    await db.notifications.insert_one({
        "notificationId": generate_id("NOTIF"),
        "userId": admin_id,
        "type": NotificationType.TRIP_ASSIGNED, 
        "title": "Collection Request",
        "message": f"New collection request from {business_name}: {estimated_quantity}kg on {preferred_date}",
        "data": {"fboId": fbo_id, "estimatedQuantity": estimated_quantity, "userId": current_user.userId},
        "isRead": False,
        "createdAt": datetime.utcnow()
    })

    # Notify Vendor (Current User)
    await db.notifications.insert_one({
        "notificationId": generate_id("NOTIF"),
        "userId": current_user.userId,
        "type": NotificationType.TRIP_ASSIGNED,
        "title": "Request Sent",
        "message": f"Your collection request for {estimated_quantity}kg on {preferred_date} has been sent.",
        "data": {"fboId": fbo_id, "requestId": request_id},
        "isRead": False,
        "createdAt": datetime.utcnow()
    })

    # Notify Assigned Collectors
    assigned_collectors = fbo.get("assignedCollectors", []) if fbo else []
    if assigned_collectors:
        notifications = []
        for collector_id in assigned_collectors:
            notifications.append({
                "notificationId": generate_id("NOTIF"),
                "userId": collector_id,
                "type": NotificationType.TRIP_ASSIGNED,
                "title": "New Collection Request",
                "message": f"New pick-up request from {business_name} ({fbo.get('address', {}).get('area', 'Unknown')}): {estimated_quantity}kg",
                "data": {"fboId": fbo_id, "estimatedQuantity": estimated_quantity, "requestId": request_id},
                "isRead": False,
                "createdAt": datetime.utcnow()
            })
        if notifications:
            await db.notifications.insert_many(notifications)

    # Send email notification
    try:
        # Notify Admin via Email
        email_setting = await db.settings.find_one({"settingKey": "supportEmail"})
        admin_email = email_setting["settingValue"] if email_setting else os.getenv("ADMIN_EMAIL", "admin@krbcleanenergy.com")
        
        await send_email(
            to_email=admin_email,
            subject=f"New Collection Request: {business_name}",
            body=f"New collection request received.\n\nFBO: {business_name}\nQuantity: {estimated_quantity} kg\nDate: {preferred_date}\n\nLogin to portal to view details."
        )

        # Notify Vendor via Email
        await send_email(
            to_email=current_user.email,
            subject="Collection Request Received",
            body=f"Your collection request has been received.\n\nQuantity: {estimated_quantity} kg\nDate: {preferred_date}\n\nOur team will contact you shortly."
        )
    except Exception as e:
        print(f"Failed to send email for collection request: {e}")

    return {
        "success": True,
        "message": "Collection request submitted successfully",
        "data": {"requestId": request_id, "status": "pending", "createdAt": datetime.utcnow()}
    }

from utils_email import send_email

@router.post("/support", response_model=Dict[str, Any])
async def create_support_ticket(
    ticket: SupportMessageCreate,
    current_user: UserOut = Depends(vendor_user)
):
    # Try exact match first, then case-insensitive
    fbo = await db.fbos.find_one({"contactPerson.email": current_user.email})
    if not fbo:
        # Try case-insensitive match
        fbo = await db.fbos.find_one({"contactPerson.email": {"$regex":f"^{current_user.email}$", "$options": "i"}})
    
    if fbo:
        fbo_id = fbo["fboId"]
    else:
        # Allow support requests even if profile is not linked
        fbo_id = "UNLINKED"
        
    ticket_id = generate_id("TKT")
    support_doc = SupportMessage(
        **ticket.dict(),
        ticketId=ticket_id,
        userId=current_user.userId,
        fboId=fbo_id
    )
    
    await db.support_messages.insert_one(support_doc.dict())
    
    # Send email notification
    try:
        # 1. Send to Sender (Confirmation)
        await send_email(
            to_email=current_user.email,
            subject=f"Copy: {ticket.subject}",
            body=f"Your message has been sent.\n\nSubject: {ticket.subject}\nMessage: {ticket.message}"
        )
        
        # 2. Send to Admin (Support Request)
        # Fetch admin/support email from settings
        email_setting = await db.settings.find_one({"settingKey": "supportEmail"})
        admin_email = email_setting["settingValue"] if email_setting else os.getenv("ADMIN_EMAIL", "admin@krbcleanenergy.com")
        
        await send_email(
            to_email=admin_email,
            subject=f"Support: {ticket.subject}",
            body=f"From: {current_user.name} ({current_user.email})\n\nTitle: {ticket.subject}\n\nMessage:\n{ticket.message}"
        )
    except Exception as e:
        print(f"Failed to send email: {e}")
        # Continue execution, do not fail the request
    
    return {
        "success": True,
        "message": "Support ticket created successfully",
        "data": {"ticketId": ticket_id}
    }

@router.get("/support", response_model=Dict[str, Any])
async def get_support_tickets(current_user: UserOut = Depends(vendor_user)):
    # Fetch tickets for the current user (regardless of FBO link)
    cursor = db.support_messages.find({"userId": current_user.userId}).sort("createdAt", -1)
    tickets = [SupportMessage(**{**doc, "id": str(doc["_id"])}) async for doc in cursor]
    
    return {
        "success": True,
        "data": tickets
    }