
from fastapi import HTTPException
from config import db

async def validate_password_policy(password: str):
    # Fetch settings
    pipeline = [
        {"$match": {"settingKey": {"$in": ["passwordMinLength", "passwordRequireUppercase", "passwordRequireNumber"]}}},
        {"$project": {"settingKey": 1, "settingValue": 1}}
    ]
    cursor = db.settings.aggregate(pipeline)
    settings = {doc["settingKey"]: doc["settingValue"] async for doc in cursor}
    
    # Defaults
    min_length = int(settings.get("passwordMinLength", 8))
    require_uppercase = str(settings.get("passwordRequireUppercase", "true")).lower() == "true"
    require_number = str(settings.get("passwordRequireNumber", "true")).lower() == "true"

    if len(password) < min_length:
        raise HTTPException(
            status_code=400, 
            detail=f"Password must be at least {min_length} characters long"
        )
    
    if require_uppercase and not any(c.isupper() for c in password):
        raise HTTPException(
            status_code=400, 
            detail="Password must contain at least one uppercase letter"
        )
    
    if require_number and not any(c.isdigit() for c in password):
        raise HTTPException(
            status_code=400, 
            detail="Password must contain at least one number"
        )
