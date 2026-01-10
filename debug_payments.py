from pymongo import MongoClient
import os
from dotenv import load_dotenv
import json

load_dotenv()

client = MongoClient(os.getenv('MONGODB_URI'))
db = client['krb_uco']

print("=== PAYMENTS ===")
payments = list(db.payments.find({}, {'_id': 0}))
print(f"Total payments: {len(payments)}\n")
for i, p in enumerate(payments):
    print(f"\nPayment {i+1}:")
    print(json.dumps(p, indent=2, default=str))
    
print("\n\n=== COLLECTIONS (PAID STATUS) ===")
collections = list(db.collections.find({'status': 'paid'}, {'_id': 0}))
print(f"Total paid collections: {len(collections)}\n")
for i, c in enumerate(collections[:3]):
    print(f"\nCollection {i+1}:")
    print(f"  collectionId: {c.get('collectionId')}")
    print(f"  fboId: {c.get('fboId')}")
    print(f" status: {c.get('status')}")
    print(f"  paymentDetails: {c.get('paymentDetails')}")
