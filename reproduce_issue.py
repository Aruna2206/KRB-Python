import asyncio
from models import FBOBase
from pydantic import ValidationError

# Mock payload based on frontend logic
mock_payload = {
    "businessName": "Test FBO",
    "contactPerson": {
        "name": "John Doe",
        "phone": "9876543210",
        "email": "john@example.com"
    },
    "address": {
        "street": "123 Test Street",
        "city": "Mumbai",
        "pincode": "400001"
    },
    "businessDetails": {
        "type": "Restaurant",
        "gstNumber": "27AAPCA1234A1Z5",
        "fssaiNumber": "12345678901234",
        "kitchenCode": "KC001",
        "fboType": "single"
    },
    "oilDetails": {
        "estimatedMonthlyUCO": 100.5,
        "storageCapacity": 200.0,
        "collectionFrequency": "weekly"
    }
}

try:
    with open("validation_output.txt", "w") as f:
        f.write("Attempting to validate mock payload...\n")
        try:
            fbo = FBOBase(**mock_payload)
            f.write("Validation SUCCESS!\n")
            f.write(fbo.json(indent=2))
        except ValidationError as e:
            f.write("Validation FAILED!\n")
            f.write(e.json())
        except Exception as e:
            f.write(f"Unexpected error: {e}")
except Exception as main_e:
    print(f"File write error: {main_e}")
