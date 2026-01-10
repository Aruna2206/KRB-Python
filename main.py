# main.py - Reload Triggered
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()  # Load environment variables

from config import db  # Import db from config
from models import *  # Import all models and enums
from dependencies import *  # Import dependencies like get_current_user
from routers import auth, admin, enrollment, collection, vendor, common, item_master

# App
app = FastAPI(title="UCO CMS API", version="1.0.0", openapi_url="/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(enrollment.router, prefix="/api/enrollment", tags=["Enrollment Team"])
app.include_router(collection.router, prefix="/api/collection", tags=["Collection Team"])
app.include_router(vendor.router, prefix="/api/vendor", tags=["Vendor/FBO"])
app.include_router(common.router, prefix="/api/common", tags=["Common/Shared"])
app.include_router(item_master.router, prefix="/api/item-master", tags=["Item Master"])

# Static Files
from fastapi.staticfiles import StaticFiles
import os
if not os.path.exists("uploads"):
    os.makedirs("uploads")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Health Check
@app.get("/db-check", tags=["Health Check"])
async def db_check():
    try:
        # Pinging the database to check connection
        await db.command('ping')
        print("Create connection successful")
        return {"status": "success", "message": "Database connection is active"}
    except Exception as e:
        print(f"Database connection failed: {e}")
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}

# Startup event for indexes
@app.on_event("startup")
async def startup_event():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("userId", unique=True)
    await db.fbos.create_index("fboId", unique=True)
    await db.fbos.create_index("assignedCollector")
    await db.fbos.create_index("address.city")
    await db.fbos.create_index("enrollmentDetails.status")
    await db.collections.create_index("collectionId", unique=True)
    await db.collections.create_index("fboId")
    await db.collections.create_index("collectorId")
    await db.trips.create_index("tripId", unique=True)
    await db.trips.create_index("collectorId")
    await db.payments.create_index("paymentId", unique=True)
    await db.payments.create_index("fboId")
    await db.notifications.create_index("userId")
    await db.pricing.create_index("qualityGrade")  # Added for pricing collection
    print("MongoDB indexes created successfully!")  # Optional: Log for verification

# Error Handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "error": exc.detail.upper().replace(" ", "_"),
            "details": {}
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)