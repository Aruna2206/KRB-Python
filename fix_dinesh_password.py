import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
import os
from dotenv import load_dotenv

load_dotenv()

# Use the same logic as config.py
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb+srv://Vercel-Admin-krb_db:gI7Oe1FH153zLRkX@krb-db.fd0fsky.mongodb.net/ucocms?retryWrites=true&w=majority")
# If env var is set, it overrides the default.
client = AsyncIOMotorClient(MONGODB_URL)
db = client.ucocms

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password):
    return pwd_context.hash(password)

async def fix_password():
    email = "dinesh@gmail.com"
    new_password = "Ram@1234"
    
    print(f"Connecting to DB...")
    # Trigger connection
    try:
        await client.admin.command('ping')
        print("Connected to MongoDB.")
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    print(f"Checking user: {email}")
    user = await db.users.find_one({"email": email})
    
    if not user:
        print("User not found!")
        return

    print(f"Found user: {user.get('userId')}")
    current_pwd = user.get('password')
    print(f"Current stored password: {current_pwd}")
    
    hashed_password = get_password_hash(new_password)
    
    print(f"Updating password to hash of: {new_password}")
    await db.users.update_one(
        {"email": email},
        {"$set": {"password": hashed_password}}
    )
    print("Password updated successfully.")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(fix_password())
