
import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from models import Role

# MongoDB connection
MONGO_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
client = AsyncIOMotorClient(MONGO_URL)
db = client.krb_db

async def analyze_data():
    print("--- Users (Role: Vendor) ---")
    async for user in db.users.find({"role": Role.VENDOR}):
        print(f"User: {user.get('name')} | Email: {user.get('email')} | ID: {user.get('_id')}")
        
        # Check if FBO exists for this user
        fbo = await db.fbos.find_one({"contactPerson.email": user.get('email')})
        if fbo:
            print(f"  -> MATCHED FBO: {fbo.get('businessName')} (ID: {fbo.get('fboId')})")
        else:
            print(f"  -> NO MATCHING FBO FOUND!")

    print("\n--- All FBOs ---")
    async for fbo in db.fbos.find():
        contact = fbo.get('contactPerson', {})
        print(f"FBO: {fbo.get('businessName')} | Contact Email: {contact.get('email')} | ID: {fbo.get('fboId')}")

if __name__ == "__main__":
    asyncio.run(analyze_data())
