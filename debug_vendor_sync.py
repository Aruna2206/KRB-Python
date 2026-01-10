
import os
from pymongo import MongoClient
import sys

# MongoDB connection
MONGO_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
client = MongoClient(MONGO_URL)
db = client.krb_db

def analyze_data():
    try:
        print("--- Users (Role: vendor) ---")
        users = list(db.users.find({"role": "vendor"}))
        print(f"Found {len(users)} vendor users.")
        
        for user in users:
            email = user.get('email')
            print(f"User: {user.get('name')} | Email: {email}")
            
            # Check if FBO exists for this user
            fbo = db.fbos.find_one({"contactPerson.email": email})
            if fbo:
                print(f"  -> MATCHED FBO: {fbo.get('businessName')}")
            else:
                print(f"  -> NO MATCHING FBO FOUND!")

        print("\n--- All FBOs ---")
        fbos = list(db.fbos.find())
        print(f"Found {len(fbos)} FBOs.")
        for fbo in fbos:
            contact = fbo.get('contactPerson', {})
            print(f"FBO: {fbo.get('businessName')} | Contact Email: {contact.get('email')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_data()
