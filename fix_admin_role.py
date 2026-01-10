import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os

# Use the same logic as config.py
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.ucocms

async def fix_admin():
    email = "admin@krbcleanenergy.com"
    print(f"Checking user: {email}")
    user = await db.users.find_one({"email": email})
    
    if not user:
        print("User not found!")
        # Optionally create it if missing? Better not assume password.
        return

    print(f"Found user. Current role: {user.get('role')}")
    
    if user.get("role") != "admin":
        print("Updating role to 'admin'...")
        await db.users.update_one(
            {"email": email},
            {"$set": {"role": "admin"}}
        )
        print("Role updated successfully.")
    else:
        print("Role is already 'admin'.")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(fix_admin())
