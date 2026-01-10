from fastapi import APIRouter, Depends, HTTPException, Query
from dependencies import get_current_user
from config import db
from models import ItemMaster, ItemMasterCreate, UserOut, PaginatedResponse
from typing import List, Optional
from datetime import datetime
import uuid

router = APIRouter()

@router.post("/", response_model=ItemMaster)
async def create_item(
    item_data: ItemMasterCreate,
    current_user: UserOut = Depends(get_current_user)
):
    try:
        # Generate ID with ITM prefix and a short random string (e.g., ITM + 8 chars of UUID)
        # Or typical timestamp based. Let's use ITM + 8 chars of UUID for uniqueness and brevity, or full UUID if collision risk is high.
        # User requested "ITM prefix". ITM-12345678 is good.
        item_id = f"ITM-{str(uuid.uuid4())[:8].upper()}"
        
        new_item = ItemMaster(
            itemId=item_id,
            **item_data.dict(),
            createdBy=current_user.userId,
            createdByName=current_user.name,
            createdAt=datetime.utcnow()
        )
        
        await db.item_master.insert_one(new_item.dict())
        return new_item
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=PaginatedResponse[ItemMaster])
async def get_items(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    created_by: Optional[str] = None
    # current_user: UserOut = Depends(get_current_user) # Optional constraint
):
    try:
        query = {}
        if search:
            query["name"] = {"$regex": search, "$options": "i"}
        
        if created_by:
            query["createdBy"] = created_by
        
        if start_date or end_date:
            date_query = {}
            if start_date:
                date_query["$gte"] = start_date
            if end_date:
                date_query["$lte"] = end_date
            if date_query:
                query["createdAt"] = date_query

        total_records = await db.item_master.count_documents(query)
        cursor = db.item_master.find(query).skip((page - 1) * limit).limit(limit).sort("createdAt", -1)
        items = await cursor.to_list(length=limit)
        
        return {
            "data": [ItemMaster(**item) for item in items],
            "pagination": {
                "currentPage": page,
                "totalPages": (total_records + limit - 1) // limit,
                "totalRecords": total_records,
                "limit": limit,
                "hasNext": page * limit < total_records,
                "hasPrevious": page > 1
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
