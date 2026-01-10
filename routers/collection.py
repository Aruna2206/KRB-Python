# routers/collection.py
from fastapi import APIRouter, Depends, Query, Form, File, UploadFile, HTTPException
from typing import List, Optional, Dict, Any
import hashlib
import os

from models import *
from dependencies import *

collection_user = require_role(Role.COLLECTION_TEAM)

router = APIRouter()

@router.get("/dashboard/stats", response_model=Dict[str, Any])
async def collection_dashboard(current_user: UserOut = Depends(collection_user)):
    today_start = datetime.combine(datetime.utcnow(), datetime.min.time())
    month_start = today_start.replace(day=1)
    
    # 1. Assigned FBOs
    assigned_fbos = await db.fbos.count_documents({"assignedCollectors": current_user.userId, "status": "active"})
    
    # 2. Today's Collections
    today_collections = await db.collections.count_documents({
        "collectorId": current_user.userId,
        "collectionDate": {"$gte": today_start}
    })
    
    # 3. Monthly Total (Quantity & Revenue)
    monthly_cursor = db.collections.aggregate([
        {
            "$match": {
                "collectorId": current_user.userId,
                "collectionDate": {"$gte": month_start}
            }
        },
        {
            "$group": {
                "_id": None,
                "totalQuantity": {"$sum": "$quantityCollected"},
                "totalRevenue": {"$sum": "$totalAmount"}
            }
        }
    ])
    monthly_result = await monthly_cursor.to_list(length=1)
    monthly_total = monthly_result[0]["totalQuantity"] if monthly_result else 0
    monthly_revenue = monthly_result[0]["totalRevenue"] if monthly_result else 0.0
    
    # 4. Average Volume (All Time)
    avg_cursor = db.collections.aggregate([
        {
            "$match": {
                "collectorId": current_user.userId
            }
        },
        {
            "$group": {
                "_id": None,
                "avgQuantity": {"$avg": "$quantityCollected"}
            }
        }
    ])
    avg_result = await avg_cursor.to_list(length=1)
    average_volume = round(avg_result[0]["avgQuantity"], 2) if avg_result else 0
    
    # 5. Recent Collections
    recent_collections_cursor = db.collections.find(
        {"collectorId": current_user.userId}
    ).sort("collectionDate", -1).limit(5)
    
    recent_collections = []
    async for c in recent_collections_cursor:
        recent_collections.append({
            "id": c.get("collectionId"),
            "fbo": c.get("fboName"),
            "volume": c.get("quantityCollected"),
            "date": c.get("collectionDate"),
            "status": c.get("status"),
            "agent": c.get("collectorName")
        })

    # 6. Quality Distribution
    quality_cursor = db.collections.aggregate([
        { "$match": { "collectorId": current_user.userId } },
        { "$group": { "_id": "$qualityGrade", "value": { "$sum": 1 } } }
    ])
    quality_dist = []
    async for doc in quality_cursor:
        quality_dist.append({"name": doc["_id"] or "Unknown", "value": doc["value"]})
        
    # 7. Status Distribution
    status_cursor = db.collections.aggregate([
        { "$match": { "collectorId": current_user.userId } },
        { "$group": { "_id": "$status", "value": { "$sum": 1 } } }
    ])
    status_dist = []
    async for doc in status_cursor:
        status_dist.append({"name": doc["_id"].title() if doc["_id"] else "Unknown", "value": doc["value"]})

    data = {
        "assignedFBOs": assigned_fbos,
        "todayCollections": today_collections,
        "monthlyTotal": monthly_total,
        "monthlyRevenue": monthly_revenue,
        "averageVolume": average_volume,
        "recentCollections": recent_collections,
        "qualityDistribution": quality_dist,
        "statusDistribution": status_dist,
        # Keep legacy keys
        "todayStats": {"collections": today_collections, "quantity": 0, "fbosVisited": 0, "kmTraveled": 0}, 
    }
    return {"success": True, "data": data}

@router.get("/pricing-settings", response_model=Dict[str, Any])
async def get_pricing_settings(current_user: UserOut = Depends(collection_user)):
    keys = ["gradeARate", "gradeBRate", "gradeCRate"]
    settings_cursor = db.settings.find({"settingKey": {"$in": keys}})
    settings = {doc["settingKey"]: doc["settingValue"] async for doc in settings_cursor}
    return {"success": True, "data": settings}

@router.get("/assigned-fbos", response_model=Dict[str, Any])
async def get_assigned_fbos(
    status: Optional[Status] = Query(None),
    search: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: UserOut = Depends(collection_user)
):
    query = {"assignedCollectors": current_user.userId}
    if status:
        query["status"] = status
    if search:
        query["$or"] = [{"businessName": {"$regex": search, "$options": "i"}}, {"fboId": {"$regex": search, "$options": "i"}}]
    
    # Date Filtering
    if start_date:
        try:
            query["createdAt"] = {"$gte": datetime.fromisoformat(start_date.replace('Z', '+00:00'))}
        except ValueError:
            pass

    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            if "createdAt" not in query:
                query["createdAt"] = {}
            query["createdAt"]["$lte"] = end_dt
        except ValueError:
            pass
    fbos = [FBO(**{**doc, "id": str(doc["_id"])}) async for doc in db.fbos.find(query)]
    return {"success": True, "data": {"fbos": fbos, "total": len(fbos)}}

@router.post("/trips/start", response_model=Dict[str, Any], status_code=201)
async def start_trip(trip_create: TripCreate, current_user: UserOut = Depends(collection_user)):
    trip_id = generate_id("TRIP")
    trip_doc = Trip(
        **trip_create.dict(),
        tripId=trip_id,
        collectorId=current_user.userId,
        collectorName=current_user.name,
        startTime=datetime.utcnow(),
        status=TripStatus.IN_PROGRESS
    )
    await db.trips.insert_one(trip_doc.dict())
    return {
        "success": True,
        "message": "Trip started successfully",
        "data": {"tripId": trip_id, "startTime": trip_doc.startTime, "plannedFBOs": len(trip_create.plannedFBOs)}
    }

@router.post("/collections", response_model=Dict[str, Any], status_code=201)
async def add_collection(
    trip_id: Optional[str] = Form(None),
    fbo_id: str = Form(...),
    quantity_collected: float = Form(...),
    quality_grade: QualityGrade = Form(...),
    quality_notes: Optional[str] = Form(None),
    container_type: Optional[ContainerType] = Form(None),
    container_count: Optional[int] = Form(None),
    container_ids: Optional[str] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    images: Optional[List[UploadFile]] = File(None),
    image_types: Optional[List[str]] = Form(None),
    amount: Optional[float] = Form(None),
    status: Optional[CollectionStatus] = Form(None),
    is_pay_now: Optional[bool] = Form(False),
    payment_method: Optional[PaymentMethod] = Form(None),
    payment_reference: Optional[str] = Form(None),
    amount_paid: Optional[float] = Form(0.0),
    payment_proof: Optional[UploadFile] = File(None),
    current_user: UserOut = Depends(collection_user)
):
    fbo = await get_object_or_404(db.fbos, "fboId", fbo_id, FBO)
    collection_id = generate_id("COL")
    container_list = container_ids.split(",") if container_ids else []
    
    images_list = []
    if images and image_types and len(images) == len(image_types):
        for img, img_type in zip(images, image_types):
            contents = await img.read()
            url = f"https://storage.example.com/collections/{collection_id}_{img_type}_{hashlib.md5(contents).hexdigest()}.jpg"
            images_list.append(CollectionImage(type=img_type, url=url))
            
    # Payment Proof Upload
    payment_proof_url = None
    if payment_proof:
        try:
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
                
            # Generate public URL (assuming server runs on localhost:8000)
            # In production, this base URL should come from env config
            payment_proof_url = f"http://localhost:8000/uploads/payments/{new_filename}"
        except Exception as e:
            print(f"Error saving payment proof: {str(e)}")
            # Fallback or just log error, but don't fail entire request?
            # It's better to fail if proof is mandatory, but here we proceed.
            pass

    location = CollectionLocation(latitude=latitude, longitude=longitude, address=fbo.address.street) if latitude and longitude else None
    # ... logic for pricing ...
    settings_cursor = db.settings.find({"settingKey": {"$in": ["gradeARate", "gradeBRate", "gradeCRate"]}})
    settings = {doc["settingKey"]: float(doc["settingValue"]) async for doc in settings_cursor}
    
    price_per_kg = 0.0
    if quality_grade == QualityGrade.A:
        price_per_kg = settings.get("gradeARate", 0.0)
    elif quality_grade == QualityGrade.B:
        price_per_kg = settings.get("gradeBRate", 0.0)
    elif quality_grade == QualityGrade.C:
        price_per_kg = settings.get("gradeCRate", 0.0)
        
    final_amount = amount if amount is not None else (quantity_collected * price_per_kg)
    
    payment_details = None
    if is_pay_now:
        payment_id = generate_id("PAY")
        balance = final_amount - (amount_paid or 0)
        
        payment_details = {
            "paymentId": payment_id,
            "paymentDate": datetime.now(timezone.utc),
            "paymentMethod": payment_method or PaymentMethod.CASH,
            "transactionReference": payment_reference or "",
            "amountPaid": amount_paid,
            "balance": balance,
            "paymentProofUrl": payment_proof_url,
            "status": PaymentStatus.PENDING,
            "history": [{
                "transactionId": generate_id("TXN"),
                "amount": amount_paid,
                "date": datetime.now(timezone.utc),
                "method": payment_method or PaymentMethod.CASH,
                "reference": payment_reference or "",
                "proofUrl": payment_proof_url,
                "paidBy": current_user.userId,
                "paidByName": current_user.name
            }]
        }
        
        # Dynamic Status Update
        if balance <= 0 and (amount_paid or 0) > 0:
            payment_details["status"] = PaymentStatus.COMPLETED
            if not status or status == CollectionStatus.PENDING:
                status = CollectionStatus.PAID

    collection_doc = Collection(
        collectionId=collection_id,
        fboId=fbo_id,
        fboName=fbo.businessName,
        collectorId=current_user.userId,
        collectorName=current_user.name,
        tripId=trip_id,
        quantityCollected=quantity_collected,
        qualityGrade=quality_grade,
        qualityNotes=quality_notes,
        containerType=container_type,
        containerCount=container_count or 0,
        containerIds=container_list,
        images=images_list,
        location=location,
        status=status or CollectionStatus.PENDING,
        pricePerKg=price_per_kg,
        totalAmount=final_amount,
        paymentDetails=payment_details
    )
    await db.collections.insert_one(collection_doc.dict())
    if trip_id:
        await db.trips.update_one(
            {"tripId": trip_id},
            {
                "$push": {
                    "completedCollections": {
                        "collectionId": collection_id,
                        "fboId": fbo_id,
                        "quantityCollected": quantity_collected,
                        "amount": final_amount,
                        "completedAt": datetime.utcnow()
                    }
                },
                "$inc": {
                    "totalQuantityCollected": quantity_collected,
                    "totalAmountCollected": final_amount or 0.0
                }
            }
        )
    await db.fbos.update_one({"fboId": fbo_id}, {"$set": {"lastCollectionDate": datetime.utcnow()}, "$inc": {"totalCollections": 1, "totalQuantityCollected": quantity_collected}})
    return {
        "success": True,
        "message": "Collection entry added successfully",
        "data": {
            "collectionId": collection_id, 
            "quantityCollected": quantity_collected, 
            "totalAmount": final_amount, 
            "status": status or CollectionStatus.PENDING,
            "paymentDetails": payment_details
        }
    }

@router.patch("/collections/{collection_id}/payment", response_model=Dict[str, Any])
async def update_collection_payment(
    collection_id: str,
    payment_method: str = Form(...),
    amount_paid: float = Form(...),
    payment_reference: Optional[str] = Form(None),
    payment_proof: Optional[UploadFile] = File(None),
    current_user: UserOut = Depends(collection_user)
):
    collection = await db.collections.find_one({"collectionId": collection_id})
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
        
    if current_user.role != Role.ADMIN and collection.get("collectorId") != current_user.userId:
        raise HTTPException(status_code=403, detail="Not authorized")

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
                
            # Generate public URL (assuming server runs on localhost:8000)
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
        "paymentDate": datetime.now(timezone.utc), # Update last payment date
        "paymentMethod": payment_method, # Update last method
        "transactionReference": payment_reference or "",
        "amountPaid": new_total_paid,
        "balance": new_balance,
        "status": PaymentStatus.PENDING,
        "paymentProofUrl": payment_proof_url, # Latest proof
        "history": history
    }
    
    updates = {"paymentDetails": payment_details}
    
    # Dynamic Status Update
    if new_balance <= 0: # Check if fully paid
        payment_details["status"] = PaymentStatus.COMPLETED
        updates["status"] = CollectionStatus.PAID
    elif new_total_paid > 0:
        payment_details["status"] = PaymentStatus.PARTIAL
        # Ensure collection status reflects it is not fully paid if it was previously marked PAID
        if collection.get("status") == CollectionStatus.PAID:
             updates["status"] = CollectionStatus.PENDING
    else:
        # No payment made or fully pending
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

@router.get("/my-collections", response_model=Dict[str, Any])
async def get_my_collections(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=1000),
    status: Optional[CollectionStatus] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    fbo_id: Optional[str] = Query(None),
    current_user: UserOut = Depends(collection_user)
):
    query = {"collectorId": current_user.userId}
    if status:
        query["status"] = status
    if fbo_id:
        query["fboId"] = fbo_id
    if start_date and end_date:
        # Append time range to date strings if they are just YYYY-MM-DD
        if len(start_date) == 10:
             start_date += "T00:00:00"
        if len(end_date) == 10:
             end_date += "T23:59:59"
        try:
             s_date = datetime.fromisoformat(start_date)
             e_date = datetime.fromisoformat(end_date)
             query["collectionDate"] = {"$gte": s_date, "$lte": e_date}
        except ValueError:
             pass # Ignore invalid date format or return error

    skip = (page - 1) * limit
    cursor = db.collections.find(query).sort("collectionDate", -1).skip(skip).limit(limit)
    collections = [Collection(**{**doc, "id": str(doc["_id"])}) async for doc in cursor]
    total = await db.collections.count_documents(query)
    
    return {
        "success": True,
        "data": {
            "collections": collections,
            "total": total,
            "page": page,
            "totalPages": (total + limit - 1) // limit
        }
    }

@router.post("/bills", response_model=Dict[str, Any], status_code=201)
async def create_bill(bill_create: BillCreate, current_user: UserOut = Depends(collection_user)):
    bill_id = generate_id("BILL")
    bill_doc = Bill(
        **bill_create.dict(),
        billId=bill_id,
        createdBy=current_user.userId,
        createdByName=current_user.name,
    )
    await db.bills.insert_one(bill_doc.dict())
    return {
        "success": True,
        "message": "Bill created successfully",
        "data": {"billId": bill_id, "billNumber": bill_create.billNumber}
    }

@router.get("/bills", response_model=Dict[str, Any])
async def get_bills(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=1000),
    fbo_id: Optional[str] = Query(None),
    current_user: UserOut = Depends(collection_user)
):
    query = {}
    if fbo_id:
        query["fboId"] = fbo_id
        
    skip = (page - 1) * limit
    cursor = db.bills.find(query).sort("createdAt", -1).skip(skip).limit(limit)
    
    # Needs to be a list of dictionaries to modify easily before Pydantic validation
    bills_raw = [doc async for doc in cursor]
    
    # Collect IDs for users who need name lookup
    user_ids_to_fetch = set()
    for doc in bills_raw:
        if not doc.get("createdByName") and doc.get("createdBy"):
             user_ids_to_fetch.add(doc["createdBy"])
             
    # Fetch Users
    user_map = {}
    if user_ids_to_fetch:
        users_cursor = db.users.find({"userId": {"$in": list(user_ids_to_fetch)}})
        async for u in users_cursor:
            user_map[u["userId"]] = u.get("name", "Unknown")
            
    # Attach names
    bills = []
    for doc in bills_raw:
        # Populate Name if missing
        if not doc.get("createdByName") and doc.get("createdBy"):
            doc["createdByName"] = user_map.get(doc["createdBy"], "Unknown")
            
        doc["id"] = str(doc["_id"])
        bills.append(Bill(**doc))

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


@router.get("/trips/active", response_model=Dict[str, Any])
async def get_active_trip(current_user: UserOut = Depends(collection_user)):
    trip = await db.trips.find_one({
        "collectorId": current_user.userId,
        "status": TripStatus.IN_PROGRESS
    })
    
    if not trip:
        return {"success": True, "data": None}
        
    return {
        "success": True, 
        "data": Trip(**{**trip, "id": str(trip["_id"])})
    }

@router.patch("/trips/{trip_id}/end", response_model=Dict[str, Any])
async def end_trip(
    trip_id: str,
    trip_end: TripEnd,
    current_user: UserOut = Depends(collection_user)
):
    trip = await get_object_or_404(db.trips, "tripId", trip_id, Trip)
    if trip.collectorId != current_user.userId:
        raise HTTPException(status_code=403, detail="Not authorized")
    total_km = trip_end.endOdometer - trip.startOdometer
    await db.trips.update_one(
        {"tripId": trip_id},
        {
            "$set": {
                "endTime": datetime.utcnow(),
                "endOdometer": trip_end.endOdometer,
                "totalKmTraveled": total_km,
                "status": TripStatus.COMPLETED,
                "updatedAt": datetime.utcnow()
            }
        }
    )
    total_qty = sum(c.quantityCollected for c in trip.completedCollections)
    return {
        "success": True,
        "message": "Trip ended successfully",
        "data": {"tripId": trip_id, "endTime": datetime.utcnow(), "totalKmTraveled": total_km, "totalCollections": len(trip.completedCollections), "totalQuantity": total_qty}
    }

@router.get("/trips/{trip_id}", response_model=Trip)
async def get_trip_details(trip_id: str, current_user: UserOut = Depends(collection_user)):
    trip = await get_object_or_404(db.trips, "tripId", trip_id, Trip)
    if trip.collectorId != current_user.userId:
        raise HTTPException(status_code=403, detail="Not authorized")
    return trip

@router.get("/my-trips", response_model=PaginatedResponse[Trip])
async def get_my_trips(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=1000),
    status: Optional[TripStatus] = Query(None),
    current_user: UserOut = Depends(collection_user)
):
    query = {"collectorId": current_user.userId}
    if status:
        query["status"] = status
    skip = (page - 1) * limit
    cursor = db.trips.find(query).sort("tripDate", -1).skip(skip).limit(limit)
    trips_list = [Trip(**{**doc, "id": str(doc["_id"])}) async for doc in cursor]
    total = await db.trips.count_documents(query)
    pagination = {
        "currentPage": page,
        "totalPages": (total + limit - 1) // limit,
        "totalRecords": total,
        "limit": limit
    }
    return PaginatedResponse(data=trips_list, pagination=pagination)

@router.get("/notifications", response_model=Dict[str, Any])
async def get_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, le=100),
    unread_only: bool = Query(False),
    current_user: UserOut = Depends(collection_user)
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

@router.patch("/bills/{bill_id}/payment", response_model=Dict[str, Any])
async def update_bill_payment(
    bill_id: str,
    payment_method: str = Form(...),
    amount_paid: float = Form(...),
    payment_reference: Optional[str] = Form(None),
    payment_proof: Optional[UploadFile] = File(None),
    current_user: UserOut = Depends(collection_user)
):
    bill = await db.bills.find_one({"billId": bill_id})
    if not bill:
        try:
            from bson import ObjectId
            bill = await db.bills.find_one({"_id": ObjectId(bill_id)})
        except:
            pass
            
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    # Payment Proof Upload
    payment_proof_url = None
    if payment_proof:
        try:
            upload_dir = "uploads/payments"
            if not os.path.exists(upload_dir):
                os.makedirs(upload_dir)
            
            filename = payment_proof.filename or "proof.jpg"
            ext = os.path.splitext(filename)[1] or ".jpg"
            contents = await payment_proof.read()
            file_hash = hashlib.md5(contents).hexdigest()
            new_filename = f"BILL_{bill_id}_proof_{file_hash}{ext}"
            file_path = os.path.join(upload_dir, new_filename)
            
            with open(file_path, "wb") as f:
                f.write(contents)
                
            payment_proof_url = f"http://localhost:8000/uploads/payments/{new_filename}"
        except Exception as e:
            print(f"Error saving payment proof: {str(e)}")

    # Update Calculations
    current_paid = float(bill.get("totalPaid", 0))
    total_amount = float(bill.get("totalAmount", 0))
    
    new_paid = current_paid + amount_paid
    new_balance = total_amount - new_paid
    if new_balance < 0: new_balance = 0
    
    # Determine Status
    status = bill.get("status", "generated")
    if new_balance <= 1.0: # Tolerance for float logic
        new_balance = 0
        status = "paid"
    elif new_paid > 0:
        status = "partial"

    # Transaction Record
    transaction = {
        "transactionId": generate_id("TXN"),
        "date": datetime.now(timezone.utc),
        "amount": amount_paid,
        "method": payment_method,
        "reference": payment_reference,
        "proofUrl": payment_proof_url,
        "recordedBy": current_user.userId
    }

    # Update DB
    await db.bills.update_one(
        {"_id": bill["_id"]},
        {
            "$set": {
                "totalPaid": new_paid,
                "totalBalance": new_balance,
                "status": status,
                "updatedAt": datetime.now(timezone.utc)
            },
            "$push": {
                "paymentHistory": transaction
            }
        }
    )

    return {
        "success": True,
        "message": "Payment recorded successfully",
        "data": {
            "billId": bill.get("billId"),
            "totalPaid": new_paid,
            "totalBalance": new_balance,
            "status": status
        }
    }
