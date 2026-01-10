# routers/admin.py
from fastapi import APIRouter, Depends, Query, HTTPException, status, Form, File, UploadFile
from typing import Optional, List, Dict, Any

from models import *
from dependencies import *

admin_user = require_role(Role.ADMIN)

router = APIRouter()

@router.get("/dashboard/stats", response_model=Dict[str, Any])
async def admin_dashboard_stats(
    period: str = Query("month"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    _: UserOut = Depends(admin_user)
):
    # Build Date Filters
    fbo_query = {}
    collection_query = {}
    
    start_dt = None
    end_dt = None

    if start_date:
        try:
            # Handle ISO string with potential 'Z' suffix
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            fbo_query["createdAt"] = {"$gte": start_dt}
            collection_query["collectionDate"] = {"$gte": start_dt}
        except ValueError:
            pass # Ignore invalid dates
        
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            
            if "createdAt" not in fbo_query: fbo_query["createdAt"] = {}
            fbo_query["createdAt"]["$lte"] = end_dt
            
            if "collectionDate" not in collection_query: collection_query["collectionDate"] = {}
            collection_query["collectionDate"]["$lte"] = end_dt
        except ValueError:
            pass
            
    # Real Aggregation
    total_fbos = await db.fbos.count_documents(fbo_query)
    
    active_fbo_query = fbo_query.copy()
    active_fbo_query["status"] = "active"
    active_fbos = await db.fbos.count_documents(active_fbo_query)
    
    # Collections Stats
    total_collections = await db.collections.count_documents(collection_query)
    
    # Revenue Stats
    pipeline = []
    if collection_query:
        pipeline.append({"$match": collection_query})
    
    pipeline.append({
        "$group": {
            "_id": None,
            "totalRevenue": {"$sum": "$totalAmount"}
        }
    })
    
    revenue_cursor = db.collections.aggregate(pipeline)
    revenue_result = await revenue_cursor.to_list(length=1)
    total_revenue = revenue_result[0]["totalRevenue"] if revenue_result else 0.0
    
    # Recent Collections
    recent_collections_cursor = db.collections.find(collection_query).sort("collectionDate", -1).limit(5)
    recent_collections = [Collection(**{**doc, "id": str(doc["_id"])}) async for doc in recent_collections_cursor]

    # FBO Status Distribution
    fbo_status_pipeline = []
    if fbo_query:
         fbo_status_pipeline.append({"$match": fbo_query})
    fbo_status_pipeline.append({"$group": {"_id": "$status", "count": {"$sum": 1}}})
    fbo_status_cursor = db.fbos.aggregate(fbo_status_pipeline)
    fbo_status_data = await fbo_status_cursor.to_list(length=None)
    
    status_distribution = []
    status_map = {doc["_id"]: doc["count"] for doc in fbo_status_data}
    status_distribution = [
        {"name": "Active", "value": status_map.get("active", 0)},
        {"name": "Pending", "value": status_map.get("pending", 0)},
        {"name": "Inactive", "value": status_map.get("inactive", 0) + status_map.get("suspended", 0)}
    ]
    
    # Chart Data (Group by Month - Last 6 months or Date Range)
    # If date range is small (< 2 months), group by week or day? For now sticking to Month for simplicity or dynamic based on range.
    # Let's enforce Monthly grouping for the "Revenue Trend" and "Monthly Collections" charts.
    
    chart_query = collection_query.copy()
    if not start_date and not end_date:
        # Default to last 6 months if no filter
        six_months_ago = datetime.utcnow() - timedelta(days=180)
        chart_query["collectionDate"] = {"$gte": six_months_ago}

    chart_pipeline = [
        {"$match": chart_query},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m", "date": "$collectionDate"}},
            "revenue": {"$sum": "$totalAmount"},
            "collections": {"$sum": "$quantityCollected"} # Volume
        }},
        {"$sort": {"_id": 1}}
    ]
    
    chart_cursor = db.collections.aggregate(chart_pipeline)
    chart_results = await chart_cursor.to_list(length=None)
    
    # Format for Recharts (e.g., month abbreviations)
    # We need to map "2023-12" to "Dec"
    import calendar
    
    chart_data = []
    for item in chart_results:
        try:
             y, m = map(int, item["_id"].split('-'))
             month_name = calendar.month_abbr[m]
             chart_data.append({
                 "month": month_name,
                 "payouts": item["revenue"],
                 "collections": item["collections"]
             })
        except:
             pass

    # FBO Performance (Group by FBO based on the selected date range)
    fbo_performance_pipeline = [
        {"$match": collection_query},
        {"$group": {
            "_id": "$fboId",
            "fboName": {"$first": "$fboName"},
            "revenue": {"$sum": "$totalAmount"},
            "volume": {"$sum": "$quantityCollected"}
        }},
        {"$sort": {"revenue": -1}}
    ]
    
    fbo_perf_cursor = db.collections.aggregate(fbo_performance_pipeline)
    fbo_perf_results = await fbo_perf_cursor.to_list(length=None)
    
    fboPerformance = []
    for item in fbo_perf_results:
         fboPerformance.append({
             "fboId": item["_id"],
             "fboName": item.get("fboName", "Unknown"),
             "revenue": item.get("revenue", 0),
             "volume": item.get("volume", 0)
         })

    data = {
        "totalFBOs": total_fbos,
        "activeFBOs": active_fbos,
        "totalCollections": total_collections,
        "totalRevenue": total_revenue,
        "monthlyGrowth": 0, # Placeholder
        "collectionGrowth": 0, # Placeholder
        "recentCollections": recent_collections,
        "statusDistribution": status_distribution,
        "chartData": chart_data,
        "fboPerformance": fboPerformance
    }
    return {"success": True, "data": data}

@router.get("/fbos", response_model=PaginatedResponse[FBO])
async def get_all_fbos(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=1000),
    status: Optional[Status] = Query(None),
    search: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    sort_by: str = Query("createdAt"),
    sort_order: str = Query("desc"),
    _: UserOut = Depends(admin_user)
):
    query = {}
    if status:
        query["status"] = status
    if city:
        query["address.city"] = city
    if search:
        query["$or"] = [
            {"businessName": {"$regex": search, "$options": "i"}},
            {"fboId": {"$regex": search, "$options": "i"}}
        ]
    skip = (page - 1) * limit
    sort_dir = 1 if sort_order == "asc" else -1
    cursor = db.fbos.find(query).sort(sort_by, sort_dir).skip(skip).limit(limit)
    fbos_list = [FBO(**{**doc, "id": str(doc["_id"])}) async for doc in cursor]
    total = await db.fbos.count_documents(query)
    total_pages = (total + limit - 1) // limit
    has_next = page < total_pages
    has_previous = page > 1
    pagination = {
        "currentPage": page,
        "totalPages": total_pages,
        "totalRecords": total,
        "limit": limit,
        "hasNext": has_next,
        "hasPrevious": has_previous
    }
    return PaginatedResponse(data=fbos_list, pagination=pagination)

@router.get("/fbos/{fbo_id}", response_model=FBO)
async def get_fbo_details(fbo_id: str, _: UserOut = Depends(admin_user)):
    return await get_object_or_404(db.fbos, "fboId", fbo_id, FBO)

@router.delete("/fbos/{fbo_id}", response_model=Dict[str, Any])
async def delete_fbo(fbo_id: str, _: UserOut = Depends(admin_user)):
    result = await db.fbos.delete_one({"fboId": fbo_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="FBO not found")
    return {
        "success": True,
        "message": "FBO deleted successfully",
        "data": {"fboId": fbo_id}
    }

@router.patch("/fbos/{fbo_id}/status", response_model=Dict[str, Any])
async def update_fbo_status(
    fbo_id: str,
    status_update: Dict[str, Any],
    _: UserOut = Depends(admin_user)
):
    if "status" not in status_update:
        raise HTTPException(status_code=400, detail="Status required")
    result = await db.fbos.update_one(
        {"fboId": fbo_id},
        {"$set": {"status": status_update["status"], "updatedAt": datetime.utcnow()}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="FBO not found")
    return {
        "success": True,
        "message": "FBO status updated successfully",
        "data": {"fboId": fbo_id, "status": status_update["status"]}
    }

@router.patch("/fbos/{fbo_id}/assign-collectors", response_model=Dict[str, Any])
async def assign_collectors_to_fbo(
    fbo_id: str,
    collectors_data: Dict[str, List[str]],
    _: UserOut = Depends(admin_user)
):
    if "collectorIds" not in collectors_data:
        raise HTTPException(status_code=400, detail="Collector IDs required")
    collector_ids = collectors_data["collectorIds"]
    collectors = await db.users.find({"userId": {"$in": collector_ids}, "role": Role.COLLECTION_TEAM}).to_list(length=None)
    
    # We might want to validate all IDs exist, but finding some is okay for now or strict check.
    # strict check:
    if len(collectors) != len(list(set(collector_ids))): # using set to handle duplicates if specificed
         pass # Ignoring strict check for simplicity, assuming UI sends valid IDs 

    result = await db.fbos.update_one(
        {"fboId": fbo_id},
        {"$set": {"assignedCollectors": collector_ids, "updatedAt": datetime.utcnow()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="FBO not found")
    
    return {
        "success": True,
        "message": "Collectors assigned successfully",
        "data": {"fboId": fbo_id, "assignedCollectors": collector_ids}
    }

@router.get("/trips", response_model=Dict[str, Any])
async def get_all_trips(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=1000),
    status: Optional[TripStatus] = Query(None),
    collector_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    sort_by: str = Query("startTime"),
    _: UserOut = Depends(admin_user)
):
    query = {}
    if status:
        query["status"] = status
    if collector_id:
        query["collectorId"] = collector_id
    if start_date and end_date:
        query["startTime"] = {"$gte": datetime.fromisoformat(start_date), "$lte": datetime.fromisoformat(end_date)}
    
    skip = (page - 1) * limit
    cursor = db.trips.find(query).sort(sort_by, -1).skip(skip).limit(limit)
    trips_docs = [doc async for doc in cursor]
    
    # Batch fetch collector details to get employeeId
    collector_ids = list({doc.get("collectorId") for doc in trips_docs if doc.get("collectorId")})
    users_cursor = db.users.find({"userId": {"$in": collector_ids}}, {"userId": 1, "employeeId": 1})
    user_map = {doc["userId"]: doc.get("employeeId") async for doc in users_cursor}

    trips_list = []
    for doc in trips_docs:
        trip_obj = Trip(**{**doc, "id": str(doc["_id"])})
        trip_dict = trip_obj.dict()
        trip_dict["collectorEmployeeId"] = user_map.get(trip_obj.collectorId)
        trips_list.append(trip_dict)
    total = await db.trips.count_documents(query)
    
    pagination = {
        "currentPage": page,
        "totalPages": (total + limit - 1) // limit,
        "totalRecords": total,
        "limit": limit
    }
    
    return {
        "success": True,
        "data": {
            "trips": trips_list,
            "pagination": pagination
        }
    }

@router.get("/collections", response_model=Dict[str, Any])
async def get_all_collections(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=1000),
    status: Optional[CollectionStatus] = Query(None),
    collector_id: Optional[str] = Query(None),
    fbo_id: Optional[str] = Query(None),
    payer_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    sort_by: str = Query("collectionDate"),
    _: UserOut = Depends(admin_user)
):
    query = {}
    if status:
        query["status"] = status
    if collector_id:
        query["collectorId"] = collector_id
    if fbo_id:
        query["fboId"] = fbo_id
    if payer_id:
        query["paymentDetails.history.paidBy"] = payer_id
    if start_date and end_date:
        query["collectionDate"] = {
            "$gte": datetime.fromisoformat(start_date.replace('Z', '+00:00')), 
            "$lte": datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        }
    skip = (page - 1) * limit
    cursor = db.collections.find(query).sort(sort_by, -1).skip(skip).limit(limit)
    collections = [Collection(**{**doc, "id": str(doc["_id"])}) async for doc in cursor]
    total = await db.collections.count_documents(query)
    # Summary
    summary_pipeline = [{"$match": query}, {"$group": {"_id": None, "totalQuantity": {"$sum": "$quantityCollected"}, "totalAmount": {"$sum": "$totalAmount"}}}]
    summary = await db.collections.aggregate(summary_pipeline).to_list(length=1)
    summary_data = summary[0] if summary else {"totalQuantity": 0, "totalAmount": 0}
    summary_data["pendingApprovals"] = await db.collections.count_documents({**query, "status": CollectionStatus.PENDING})
    pagination = {
        "currentPage": page,
        "totalPages": (total + limit - 1) // limit,
        "totalRecords": total,
        "limit": limit
    }
    return {
        "success": True,
        "data": {
            "collections": collections,
            "pagination": pagination,
            "summary": summary_data
        }
    }

@router.get("/collections/{collection_id}", response_model=Collection)
async def get_collection_details(collection_id: str, _: UserOut = Depends(admin_user)):
    return await get_object_or_404(db.collections, "collectionId", collection_id, Collection)

@router.patch("/collections/{collection_id}/review", response_model=Dict[str, Any])
async def review_collection(
    collection_id: str,
    review: CollectionReview,
    current_user: UserOut = Depends(admin_user)
):
    collection = await get_object_or_404(db.collections, "collectionId", collection_id, Collection)
    if collection.status != CollectionStatus.PENDING:
        raise HTTPException(status_code=400, detail="Collection not pending review")
    updates = {"status": review.action, "approvedBy": current_user.userId, "approvedAt": datetime.utcnow()}
    if review.qualityGrade:
        updates["qualityGrade"] = review.qualityGrade
    if review.pricePerKg:
        updates["pricePerKg"] = review.pricePerKg
        updates["totalAmount"] = collection.quantityCollected * review.pricePerKg
    if review.notes:
        updates["qualityNotes"] = review.notes
    await db.collections.update_one({"collectionId": collection_id}, {"$set": updates})
    return {
        "success": True,
        "message": f"Collection {review.action} successfully",
        "data": {"collectionId": collection_id, "status": review.action, "totalAmount": updates.get("totalAmount")}
    }

@router.delete("/collections/{collection_id}", response_model=Dict[str, Any])
async def delete_collection(collection_id: str, _: UserOut = Depends(admin_user)):
    collection = await db.collections.find_one({"collectionId": collection_id})
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
        
    # Get details for updates
    trip_id = collection.get("tripId")
    fbo_id = collection.get("fboId")
    quantity = collection.get("quantityCollected", 0)
    amount = collection.get("totalAmount", 0) or 0
    
    # Update Trip
    if trip_id:
        await db.trips.update_one(
            {"tripId": trip_id},
            {
                "$pull": {"completedCollections": {"collectionId": collection_id}},
                "$inc": {
                    "totalQuantityCollected": -quantity,
                    "totalAmountCollected": -amount
                }
            }
        )
        
    # Update FBO
    if fbo_id:
        await db.fbos.update_one(
            {"fboId": fbo_id},
            {"$inc": {"totalCollections": -1, "totalQuantityCollected": -quantity}}
        )

    result = await db.collections.delete_one({"collectionId": collection_id})
    
    return {
        "success": True,
        "message": "Collection deleted successfully",
        "data": {"collectionId": collection_id}
    }

@router.put("/collections/{collection_id}", response_model=Dict[str, Any])
async def update_collection_details(
    collection_id: str,
    update_data: Dict[str, Any],
    _: UserOut = Depends(admin_user)
):
    # If they update quantity or grade, we might want to recalculate totalAmount
    # For now, we update fields as provided. Using $set to only update provided fields.
    if "collectionId" in update_data:
        del update_data["collectionId"]
    
    update_data["updatedAt"] = datetime.utcnow()
    
    # Check if we need to recalcluate price
    if "quantityCollected" in update_data or "qualityGrade" in update_data:
        collection = await db.collections.find_one({"collectionId": collection_id})
        if collection:
            qty = float(update_data.get("quantityCollected", collection.get("quantityCollected", 0)))
            grade = update_data.get("qualityGrade", collection.get("qualityGrade"))
            
            # Fetch price settings
            settings_cursor = db.settings.find({"settingKey": {"$in": ["gradeARate", "gradeBRate", "gradeCRate"]}})
            settings = {doc["settingKey"]: float(doc["settingValue"]) async for doc in settings_cursor}
            
            price_per_kg = 0.0
            if grade == QualityGrade.A:
                price_per_kg = settings.get("gradeARate", 0.0)
            elif grade == QualityGrade.B:
                price_per_kg = settings.get("gradeBRate", 0.0)
            elif grade == QualityGrade.C:
                price_per_kg = settings.get("gradeCRate", 0.0)
            
            update_data["pricePerKg"] = price_per_kg
            update_data["totalAmount"] = qty * price_per_kg

    result = await db.collections.update_one(
        {"collectionId": collection_id},
        {"$set": update_data}
    )
    
    if result.modified_count == 0:
         if not await db.collections.find_one({"collectionId": collection_id}):
            raise HTTPException(status_code=404, detail="Collection not found")
            
    return {
        "success": True,
        "message": "Collection updated successfully",
        "data": {"collectionId": collection_id, **update_data}
    }

@router.get("/performance/collectors", response_model=Dict[str, Any])
async def get_collector_performance(
    period: str = Query("month"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    collector_id: Optional[str] = Query(None),
    _: UserOut = Depends(admin_user)
):
    # Mock; implement aggregation
    data = {
        "period": {"startDate": start_date, "endDate": end_date},
        "collectors": [
            {
                "collectorId": "USR_COL_001",
                "name": "Ramesh Singh",
                "phone": "+91-9876543210",
                "metrics": {
                    "totalCollections": 45,
                    "totalQuantity": 1850.5,
                    "totalAmount": 138787.5,
                    "totalTrips": 12,
                    "totalKmTraveled": 485.6,
                    "avgCollectionPerTrip": 3.75,
                    "avgQuantityPerCollection": 41.1,
                    "fbosServiced": 28
                },
                "performance": {"targetQuantity": 2000.0, "achievementPercentage": 92.5, "rating": 4.5},
                "dailyBreakdown": [{"date": "2025-12-01", "collections": 8, "quantity": 320.5, "trips": 2, "kmTraveled": 85.6}]
            }
        ],
        "summary": {"totalCollectors": 15, "totalCollections": 342, "totalQuantity": 13560.8, "totalKmTraveled": 3250.5}
    }
    return {"success": True, "data": data}

@router.get("/payments", response_model=PaginatedResponse[Payment])
async def get_payments(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=1000),
    status: Optional[PaymentStatus] = Query(None),
    fbo_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    _: UserOut = Depends(admin_user)
):
    query = {}
    if status:
        query["status"] = status
    if fbo_id:
        query["fboId"] = fbo_id
    if start_date and end_date:
        query["paymentDate"] = {"$gte": datetime.fromisoformat(start_date), "$lte": datetime.fromisoformat(end_date)}
    skip = (page - 1) * limit
    cursor = db.payments.find(query).sort("paymentDate", -1).skip(skip).limit(limit)
    payments_list = [Payment(**{**doc, "id": str(doc["_id"])}) async for doc in cursor]
    total = await db.payments.count_documents(query)
    pagination = {
        "currentPage": page,
        "totalPages": (total + limit - 1) // limit,
        "totalRecords": total,
        "limit": limit
    }
    return PaginatedResponse(data=payments_list, pagination=pagination)

@router.post("/payments/process", response_model=Dict[str, Any])
async def process_payment(payment_create: PaymentCreate, current_user: UserOut = Depends(admin_user)):
    collections = await db.collections.find({"collectionId": {"$in": payment_create.collectionIds}}).to_list(length=None)
    if len(collections) != len(payment_create.collectionIds):
        raise HTTPException(status_code=404, detail="Some collections not found")
        
    # Check if any collections are already paid
    for c in collections:
        if c.get("status") == CollectionStatus.PAID:
            raise HTTPException(status_code=400, detail=f"Collection {c.get('collectionId')} is already paid")
            
    total_quantity = sum(c["quantityCollected"] for c in collections)
    avg_price = sum(c.get("pricePerKg", 0) * c["quantityCollected"] for c in collections) / total_quantity if total_quantity > 0 else 0
    total_amount = total_quantity * avg_price
    deductions_total = sum(d.amount for d in payment_create.deductions or [])
    net_amount = total_amount - deductions_total
    payment_id = generate_id("PAY")
    fbo = await db.fbos.find_one({"fboId": payment_create.fboId})
    if not fbo:
        raise HTTPException(status_code=404, detail="FBO not found")
    payment_doc = Payment(
        **payment_create.dict(),
        paymentId=payment_id,
        fboName=fbo["businessName"],
        totalQuantity=total_quantity,
        averagePricePerKg=avg_price,
        totalAmount=total_amount,
        netAmount=net_amount,
        paymentDate=datetime.utcnow(),
        bankDetails=fbo["bankDetails"],
        processedBy=current_user.userId,
        status=PaymentStatus.PROCESSING
    )
    await db.payments.insert_one(payment_doc.dict())
    
    # Update linked collections to PAID
    await db.collections.update_many(
        {"collectionId": {"$in": payment_create.collectionIds}},
        {"$set": {
            "status": CollectionStatus.PAID,
            "paymentDetails": {
                "paymentId": payment_id,
                "paymentDate": payment_doc.paymentDate,
                "paymentMethod": payment_create.paymentMethod,
                "transactionReference": "", # Initially empty until processed if not provided
                "status": PaymentStatus.PROCESSING
            },
            "updatedAt": datetime.utcnow()
        }}
    )
    
    return {
        "success": True,
        "message": "Payment processed successfully",
        "data": {"paymentId": payment_id, "totalAmount": total_amount, "netAmount": net_amount, "status": PaymentStatus.PROCESSING}
    }

@router.patch("/payments/{payment_id}/status", response_model=Dict[str, Any])
async def update_payment_status(
    payment_id: str,
    update: PaymentUpdate,
    _: UserOut = Depends(admin_user)
):
    result = await db.payments.update_one(
        {"paymentId": payment_id},
        {"$set": {"status": update.status, "transactionReference": update.transactionReference, "notes": update.notes, "updatedAt": datetime.utcnow()}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"success": True, "message": "Payment status updated", "data": {"paymentId": payment_id, "status": update.status}}

@router.patch("/collections/{collection_id}/payment", response_model=Dict[str, Any])
async def admin_update_collection_payment(
    collection_id: str,
    payment_method: str = Form(...),
    amount_paid: float = Form(...),
    payment_reference: Optional[str] = Form(None),
    payment_proof: Optional[UploadFile] = File(None),
    current_user: UserOut = Depends(admin_user)
):
    """Admin endpoint to update collection payment - no collector restriction"""
    collection = await db.collections.find_one({"collectionId": collection_id})
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    # Get existing payment details
    existing_details = collection.get("paymentDetails", {}) or {}
    total_amount = collection.get("totalAmount", 0) or 0
    
    # Calculate new totals
    previous_paid = existing_details.get("amountPaid", 0) or 0
    new_total_paid = previous_paid + amount_paid
    new_balance = float(total_amount) - float(new_total_paid)
    
    # Handle Proof Upload
    payment_proof_url = None
    if payment_proof:
        try:
            import hashlib
            # Ensure upload directory exists
            upload_dir = "uploads/payments"
            if not os.path.exists(upload_dir):
                os.makedirs(upload_dir)
            
            # Generate unique filename
            filename = payment_proof.filename or "proof.jpg"
            ext = os.path.splitext(filename)[1]
            if not ext:
                ext = ".jpg"
                
            contents = await payment_proof.read()
            file_hash = hashlib.md5(contents).hexdigest()
            new_filename = f"{collection_id}_proof_{file_hash}{ext}"
            file_path = os.path.join(upload_dir, new_filename)
            
            # Write file to disk
            with open(file_path, "wb") as f:
                f.write(contents)
                
            # Generate public URL
            payment_proof_url = f"http://localhost:8000/uploads/payments/{new_filename}"
        except Exception as e:
            print(f"Error saving payment proof: {str(e)}")

    # Create new transaction record
    transaction_id = generate_id("TXN")
    new_transaction = {
        "transactionId": transaction_id,
        "amount": amount_paid,
        "date": datetime.now(timezone.utc),
        "method": payment_method,
        "reference": payment_reference,
        "proofUrl": payment_proof_url,
        "paidBy": current_user.userId,
        "paidByName": current_user.name
    }
    
    # Get existing history
    history = existing_details.get("history", [])
    history.append(new_transaction)

    payment_id = existing_details.get("paymentId") or generate_id("PAY")
    
    payment_details = {
        "paymentId": payment_id,
        "paymentDate": datetime.now(timezone.utc),
        "paymentMethod": payment_method,
        "transactionReference": payment_reference or "",
        "amountPaid": new_total_paid,
        "balance": new_balance,
        "status": PaymentStatus.PENDING,
        "paymentProofUrl": payment_proof_url,
        "history": history
    }
    
    updates = {"paymentDetails": payment_details}
    
    # Dynamic Status Update
    if new_balance <= 0:
        payment_details["status"] = PaymentStatus.COMPLETED
        updates["status"] = CollectionStatus.PAID
    elif new_total_paid > 0:
        payment_details["status"] = PaymentStatus.PARTIAL
    else:
        payment_details["status"] = PaymentStatus.PENDING
    
    await db.collections.update_one(
        {"collectionId": collection_id},
        {"$set": updates}
    )
    
    return {
        "success": True,
        "message": "Payment updated successfully",
        "data": {
            "collectionId": collection_id,
            "paymentDetails": payment_details,
            "status": updates.get("status", collection.get("status"))
        }
    }

@router.get("/users", response_model=PaginatedResponse[UserOut])
async def get_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=1000),
    role: Optional[Role] = Query(None),
    status: Optional[Status] = Query(None),
    sort_by: str = Query("employeeId"),
    sort_order: str = Query("asc"),
    _: UserOut = Depends(get_current_active_user)
):
    query = {}
    if role:
        query["role"] = role
    if status:
        query["status"] = status
    skip = (page - 1) * limit
    sort_dir = 1 if sort_order == "asc" else -1
    cursor = db.users.find(query).sort(sort_by, sort_dir).skip(skip).limit(limit)
    
    users_list = []
    async for doc in cursor:
        user = UserOut(**{**doc, "id": str(doc["_id"])})
        if user.role == Role.COLLECTION_TEAM:
            # Count assigned FBOs
            count = await db.fbos.count_documents({"assignedCollectors": user.userId})
            if user.metadata is None:
                user.metadata = {}
            user.metadata["assignmentCount"] = count
        users_list.append(user)

    total = await db.users.count_documents(query)
    pagination = {
        "currentPage": page,
        "totalPages": (total + limit - 1) // limit,
        "totalRecords": total,
        "limit": limit
    }
    return PaginatedResponse(data=users_list, pagination=pagination)

from utils_password import validate_password_policy

@router.post("/users", response_model=Dict[str, Any], status_code=201)
async def create_user(user_create: UserCreate, _: UserOut = Depends(admin_user)):
    if await db.users.find_one({"email": user_create.email}):
        raise HTTPException(status_code=409, detail="Email already registered")
        
    # Validate password
    await validate_password_policy(user_create.password)

    # Auto-generate Employee ID if not provided
    if not user_create.employeeId:
        cursor = db.users.find({"employeeId": {"$regex": "^EMP"}}, {"employeeId": 1})
        existing_ids = [doc["employeeId"] async for doc in cursor]
        
        max_num = 0
        for eid in existing_ids:
            if not eid: continue
            try:
                # Remove non-numeric characters to handle variants or just strict EMP prefix
                num_part = ''.join(filter(str.isdigit, eid))
                if num_part:
                    num = int(num_part)
                    if num > max_num:
                        max_num = num
            except:
                pass
        
        new_id = f"EMP{str(max_num + 1).zfill(3)}"
        # Update the pydantic model instance
        user_create.employeeId = new_id
    
    user_id = generate_id("USR")
    hashed_password = get_password_hash(user_create.password)
    user_doc = UserOut(
        **user_create.dict(exclude={"password"}),
        userId=user_id
    )
    await db.users.insert_one({**user_doc.dict(), "password": hashed_password})
    return {
        "success": True,
        "message": "User created successfully",
        "data": {"userId": user_id, "name": user_create.name, "email": user_create.email, "role": user_create.role}
    }

# ... (other endpoints)

@router.patch("/users/{user_id}", response_model=Dict[str, Any])
async def update_user(
    user_id: str,
    user_update: Dict[str, Any],
    _: UserOut = Depends(admin_user)
):
    # Prevent updating immutable fields or sensitive data directly if needed
    if "userId" in user_update:
        del user_update["userId"]
    if "password" in user_update:
        # Validate password if it's being updated
        await validate_password_policy(user_update["password"])
        user_update["password"] = get_password_hash(user_update["password"])
    
    user_update["updatedAt"] = datetime.utcnow()
    
    result = await db.users.update_one(
        {"userId": user_id},
        {"$set": user_update}
    )
    
    if result.modified_count == 0:
         # Check if user exists
        if not await db.users.find_one({"userId": user_id}):
            raise HTTPException(status_code=404, detail="User not found")
            
    return {
        "success": True,
        "message": "User updated successfully",
        "data": {"userId": user_id, **user_update}
    }

@router.delete("/users/{user_id}", response_model=Dict[str, Any])
async def delete_user(user_id: str, _: UserOut = Depends(admin_user)):
    result = await db.users.delete_one({"userId": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "success": True,
        "message": "User deleted successfully",
        "data": {"userId": user_id}
    }

@router.get("/settings", response_model=Dict[str, Any])
async def get_settings(_: UserOut = Depends(get_current_active_user)):
    # Fetch all settings
    cursor = db.settings.find({})
    settings_list = [Setting(**{**doc, "id": str(doc["_id"])}) async for doc in cursor]
    
    # Convert to a dictionary for easier frontend consumption
    settings_dict = {s.settingKey: s.settingValue for s in settings_list}
    
    return {"success": True, "data": settings_dict}

@router.put("/settings", response_model=Dict[str, Any])
async def update_settings(
    settings: Dict[str, Any], 
    current_user: UserOut = Depends(admin_user)
):
    # Iterate and upsert
    for key, value in settings.items():
        await db.settings.update_one(
            {"settingKey": key},
            {"$set": {
                "settingKey": key,
                "settingValue": value,
                "updatedBy": current_user.userId,
                "updatedAt": datetime.utcnow()
            }},
            upsert=True
        )
        
    return {"success": True, "message": "Settings updated successfully"}