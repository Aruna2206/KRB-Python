# routers/enrollment.py
from fastapi import APIRouter, Depends, Query, UploadFile, File, Form, HTTPException
from typing import List, Dict, Any

from models import *
from dependencies import *
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta

enrollment_user = require_role(Role.ENROLLMENT_TEAM)

router = APIRouter()

@router.get("/dashboard/stats", response_model=Dict[str, Any])
async def enrollment_dashboard(
    current_user: UserOut = Depends(enrollment_user),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None)
):
    # Show stats for the current user 
    match_query = {"enrollmentDetails.enrolledBy": current_user.userId}

    if start_date:
        if "enrollmentDetails.enrolledAt" not in match_query:
            match_query["enrollmentDetails.enrolledAt"] = {}
        match_query["enrollmentDetails.enrolledAt"]["$gte"] = start_date
    
    if end_date:
        if "enrollmentDetails.enrolledAt" not in match_query:
            match_query["enrollmentDetails.enrolledAt"] = {}
        match_query["enrollmentDetails.enrolledAt"]["$lte"] = end_date

    total_enrolled = await db.fbos.count_documents(match_query)
    
    active_query = match_query.copy()
    active_query["status"] = Status.ACTIVE
    active_clients = await db.fbos.count_documents(active_query)
    
    pending_query = match_query.copy()
    pending_query["status"] = Status.PENDING
    pending_approvals = await db.fbos.count_documents(pending_query)
    
    # Calculate enrolled this month
    now = datetime.utcnow()
    start_of_month = datetime(now.year, now.month, 1)
    
    month_query = match_query.copy()
    month_query["enrollmentDetails.enrolledAt"] = {"$gte": start_of_month}
    enrolled_this_month = await db.fbos.count_documents(month_query)

    # Calculate enrolled last month for growth insight
    start_of_last_month = start_of_month - relativedelta(months=1)
    end_of_last_month = start_of_month - timedelta(seconds=1)
    last_month_query = match_query.copy()
    last_month_query["enrollmentDetails.enrolledAt"] = {"$gte": start_of_last_month, "$lte": end_of_last_month}
    enrolled_last_month = await db.fbos.count_documents(last_month_query)

    growth_percentage = 0
    if enrolled_last_month > 0:
        growth_percentage = int(((enrolled_this_month - enrolled_last_month) / enrolled_last_month) * 100)
    elif enrolled_this_month > 0:
        growth_percentage = 100 # 100% growth if started from 0

    months_dict = {}
    for i in range(5, -1, -1):
        d = now - relativedelta(months=i)
        key = d.strftime("%Y-%m")
        months_dict[key] = 0

    trend_pipeline = [
        {"$match": match_query},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m", "date": "$enrollmentDetails.enrolledAt"}},
            "count": {"$sum": 1}
        }}
    ]
    trend_cursor = db.fbos.aggregate(trend_pipeline)
    async for doc in trend_cursor:
        if doc["_id"] in months_dict:
            months_dict[doc["_id"]] = doc["count"]

    # Recent Enrollments
    recent_cursor = db.fbos.find(match_query).sort("enrollmentDetails.enrolledAt", -1).limit(5)
    recent_enrollments = []
    async for fbo in recent_cursor:
        recent_enrollments.append({
            "fboId": fbo.get("fboId"),
            "businessName": fbo.get("businessName"),
            "contactPerson": fbo.get("contactPerson"),
            "businessDetails": fbo.get("businessDetails"),
            "address": fbo.get("address"),
            "category": fbo.get("category"),
            "createdAt": fbo.get("enrollmentDetails", {}).get("enrolledAt") or fbo.get("createdAt"),
            "status": fbo.get("status")
        })

    import calendar
    chart_data = []
    for key, val in months_dict.items():
        y, m = map(int, key.split('-'))
        chart_data.append({
            "name": calendar.month_abbr[m],
            "enrollments": val,
            "active": int(val * 0.8) # Heuristic: 80% become active
        })

    # Weekly Performance (Last 4 weeks)
    weekly_data = []
    current_week_achieved = 0
    WEEKLY_TARGET = 12
    
    for i in range(3, -1, -1):
        week_start = now - timedelta(days=now.weekday()) - timedelta(weeks=i)
        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        
        # Adjust start/end for query
        # Using simple 7-day windows back from now might be easier but sticking to calendar weeks logic
        # Or simplistic approach:
        w_start = now - timedelta(weeks=i + 1)
        w_end = now - timedelta(weeks=i)
        
        w_query = match_query.copy()
        w_query["enrollmentDetails.enrolledAt"] = {"$gte": w_start, "$lt": w_end}
        count = await db.fbos.count_documents(w_query)
        weekly_data.append({
            "name": f"Week {4-i}",
            "target": WEEKLY_TARGET, 
            "achieved": count
        })
        if i == 0:
            current_week_achieved = count

    # Insights
    insights = {
        "growth": {
            "type": "increase" if growth_percentage >= 0 else "decrease",
            "percentage": abs(growth_percentage),
            "message": f"Enrollments represent a {abs(growth_percentage)}% {'increase' if growth_percentage >= 0 else 'decrease'} from last month."
        },
        "target": {
            "percentage": int((current_week_achieved / WEEKLY_TARGET) * 100) if WEEKLY_TARGET > 0 else 0,
            "message": f"You have achieved {int((current_week_achieved / WEEKLY_TARGET) * 100) if WEEKLY_TARGET > 0 else 0}% of your weekly target."
        }
    }

    data = {
        "totalEnrolled": total_enrolled,
        "activeClients": active_clients,
        "pendingApprovals": pending_approvals,
        "achieved": enrolled_this_month,
        "monthlyTarget": 50,
        "trendData": chart_data,
        "performanceData": weekly_data,
        "recentEnrollments": recent_enrollments,
        "insights": insights
    }
    return {"success": True, "data": data}

@router.post("/fbos", response_model=Dict[str, Any], status_code=201)
async def create_fbo(fbo_base: FBOBase, current_user: UserOut = Depends(enrollment_user)):
    if await db.fbos.find_one({"businessName": fbo_base.businessName, "status": {"$ne": Status.INACTIVE}}):
        raise HTTPException(status_code=409, detail="FBO with this name already exists")
    fbo_id = generate_id("FBO")
    fbo_doc = FBO(
        **fbo_base.dict(exclude={"status"}),
        fboId=fbo_id,
        enrollmentDetails=FBOEnrollmentDetails(
            enrolledBy=current_user.userId,
            enrolledByName=current_user.name,
            enrolledByRole=current_user.role,
            status=fbo_base.status or Status.PENDING
        ),
        status=fbo_base.status or Status.PENDING
    )
    await db.fbos.insert_one(fbo_doc.dict())
    return {
        "success": True,
        "message": "FBO enrolled successfully",
        "data": {
            "fboId": fbo_id, 
            "businessName": fbo_base.businessName, 
            "status": Status.PENDING, 
            "enrolledAt": fbo_doc.enrollmentDetails.enrolledAt,
            "enrolledBy": current_user.name,
            "role": current_user.role
        }
    }

@router.post("/fbos/{fbo_id}/documents")
async def upload_fbo_documents(
    fbo_id: str,
    files: List[UploadFile] = File(...),
    document_types: List[str] = Form(...),
    _: UserOut = Depends(enrollment_user)
):
    if len(files) != len(document_types):
        raise HTTPException(status_code=400, detail="Number of files and types must match")
    fbo = await get_object_or_404(db.fbos, "fboId", fbo_id, FBO)
    documents = []
    import hashlib
    for file, doc_type in zip(files, document_types):
        contents = await file.read()
        url = f"https://storage.example.com/documents/{fbo_id}_{doc_type}_{hashlib.md5(contents).hexdigest()}.pdf"
        documents.append(FBODocument(type=doc_type, url=url))
        await db.fbos.update_one(
            {"fboId": fbo_id},
            {"$push": {"documents": {"type": doc_type, "url": url, "uploadedAt": datetime.utcnow()}}}
        )
    return {"success": True, "message": "Documents uploaded successfully", "data": {"documents": documents}}

@router.get("/list", response_model=PaginatedResponse[FBO])
async def get_my_enrollments(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=100),
    status: Optional[Status] = Query(None),
    current_user: UserOut = Depends(enrollment_user)
):
    query = {"enrollmentDetails.enrolledBy": current_user.userId}
    if status:
        query["enrollmentDetails.status"] = status
    skip = (page - 1) * limit
    cursor = db.fbos.find(query).sort("enrollmentDetails.enrolledAt", -1).skip(skip).limit(limit)
    enrollments = [FBO(**{**doc, "id": str(doc["_id"])}) async for doc in cursor]
    total = await db.fbos.count_documents(query)
    pagination = {
        "currentPage": page,
        "totalPages": (total + limit - 1) // limit,
        "totalRecords": total,
        "limit": limit
    }
    return PaginatedResponse(data=enrollments, pagination=pagination)

@router.put("/fbos/{fbo_id}", response_model=Dict[str, Any])
async def update_fbo_details(
    fbo_id: str,
    fbo_update: Dict[str, Any],
    current_user: UserOut = Depends(enrollment_user)
):
    fbo = await get_object_or_404(db.fbos, "fboId", fbo_id, FBO)
    if fbo.enrollmentDetails.enrolledBy != current_user.userId and current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to update this FBO")
    await db.fbos.update_one({"fboId": fbo_id}, {"$set": {**fbo_update, "updatedAt": datetime.utcnow()}})
    return {"success": True, "message": "FBO details updated successfully", "data": {"fboId": fbo_id, "updatedAt": datetime.utcnow()}}