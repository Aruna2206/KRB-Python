# config.py
import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb+srv://Vercel-Admin-krb_db:gI7Oe1FH153zLRkX@krb-db.fd0fsky.mongodb.net/ucocms?retryWrites=true&w=majority")
client = AsyncIOMotorClient(MONGODB_URL)
db = client.ucocms  # Database name