# models.py
from datetime import datetime, timezone
from typing import List, Optional, Any, Dict, Generic, TypeVar
from enum import Enum
from pydantic import BaseModel, Field, EmailStr, validator
from bson import ObjectId

T = TypeVar('T', bound=BaseModel)

class PaginatedResponse(BaseModel, Generic[T]):
    data: List[T]
    pagination: Dict[str, Any] = {
        "currentPage": 1,
        "totalPages": 0,
        "totalRecords": 0,
        "limit": 20,
        "hasNext": False,
        "hasPrevious": False
    }

# Enums
class Role(str, Enum):
    ADMIN = "admin"
    ENROLLMENT_TEAM = "enrollment_team"
    COLLECTION_TEAM = "collection_team"
    FBO = "fbo"

class Status(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING = "pending"
    VERIFIED = "verified"

class QualityGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    REJECTED = "Rejected"

class CollectionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"

class TripStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class PaymentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"

class NotificationType(str, Enum):
    COLLECTION_APPROVED = "collection_approved"
    PAYMENT_PROCESSED = "payment_processed"
    NEW_FBO = "new_fbo"
    TRIP_ASSIGNED = "trip_assigned"

class BusinessType(str, Enum):
    RESTAURANT = "restaurant"
    HOTEL = "hotel"
    CLOUD_KITCHEN = "cloud_kitchen"
    MESS = "mess"
    CANTEEN = "canteen"
    CATERING = "catering"
    MANUFACTURER = "manufacturer"
    STREET_VENDOR = "street_vendor"
    OTHER = "other"

class ContainerType(str, Enum):
    DRUM = "Drum"
    JERRY_CAN = "Jerry Can"
    IBC_TANK = "IBC Tank"

class PaymentMethod(str, Enum):
    CASH = "Cash"
    BANK_TRANSFER = "Bank Transfer"
    UPI = "UPI"
    CHEQUE = "Cheque"

class CollectionFrequency(str, Enum):
    WEEKLY = "weekly"
    BI_WEEKLY = "bi-weekly"
    MONTHLY = "monthly"

# User Models
class UserBase(BaseModel):
    name: str
    email: EmailStr
    phone: str
    role: Role
    status: Status = Status.ACTIVE
    employeeId: Optional[str] = None
    profileImage: Optional[str] = None
    permissions: Optional[List[str]] = []
    metadata: Optional[Dict[str, Any]] = {}

class UserCreate(UserBase):
    password: str

    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v

class UserOut(UserBase):
    userId: str
    id: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)
    lastLogin: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class UserLogin(BaseModel):
    email: EmailStr
    password: str
    role: Optional[Role] = None

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    profileImage: Optional[str] = None

# FBO Models
class FBOContact(BaseModel):
    name: str
    designation: Optional[str] = None
    phone: str
    alternatePhone: Optional[str] = None
    email: EmailStr

class FBOAddress(BaseModel):
    street: str
    area: Optional[str] = None
    city: str
    state: Optional[str] = None
    pincode: str
    landmark: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    mapLink: Optional[str] = None

class FBOBusinessDetails(BaseModel):
    type: BusinessType
    gstNumber: str
    fssaiNumber: str
    kitchenCode: Optional[str] = None
    panNumber: Optional[str] = None
    aadharNumber: Optional[str] = None
    establishmentYear: Optional[int] = None
    seatingCapacity: Optional[int] = None

    avgDailyFootfall: Optional[int] = None
    fboType: Optional[str] = None

class FBOOilDetails(BaseModel):
    estimatedMonthlyUCO: float
    currentStorage: str = "Plastic Drums"
    storageCapacity: float
    collectionFrequency: CollectionFrequency
    pricePerKg: Optional[float] = None
    disposalProducts: Optional[List[str]] = []

class FBOBankDetails(BaseModel):
    accountHolderName: str
    accountNumber: str
    bankName: str
    ifscCode: str
    branch: str
    accountType: str = "Current"

class FBODocument(BaseModel):
    type: str
    url: str
    uploadedAt: datetime = Field(default_factory=datetime.utcnow)

class FBOEnrollmentDetails(BaseModel):
    enrolledBy: str
    enrolledByName: Optional[str] = None
    enrolledByRole: Optional[Role] = None
    enrolledAt: datetime = Field(default_factory=datetime.utcnow)
    verifiedBy: Optional[str] = None
    verifiedAt: Optional[datetime] = None
    status: Status = Status.PENDING

class FBOBase(BaseModel):
    businessName: str
    contactPerson: FBOContact
    address: FBOAddress
    businessDetails: FBOBusinessDetails
    oilDetails: FBOOilDetails
    bankDetails: Optional[FBOBankDetails] = None
    status: Optional[Status] = None
    documents: Optional[List[FBODocument]] = []
    assignedCollectors: Optional[List[str]] = []

class FBO(FBOBase):
    fboId: str
    id: Optional[str] = None
    enrollmentDetails: FBOEnrollmentDetails
    assignedCollectors: Optional[List[str]] = []
    lastCollectionDate: Optional[datetime] = None
    totalCollections: int = 0
    totalQuantityCollected: float = 0.0
    totalAmountPaid: float = 0.0
    status: Status = Status.PENDING
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

# Collection Models
class CollectionContainerDetails(BaseModel):
    containerType: ContainerType
    containerCount: int
    containerIds: List[str]

class CollectionImage(BaseModel):
    type: str
    url: str
    uploadedAt: datetime = Field(default_factory=datetime.utcnow)

class CollectionLocation(BaseModel):
    latitude: float
    longitude: float
    address: str

class PaymentTransaction(BaseModel):
    transactionId: str
    amount: float
    date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    method: str
    reference: Optional[str] = None
    proofUrl: Optional[str] = None
    paidBy: Optional[str] = None
    paidByName: Optional[str] = None

class PaymentDetails(BaseModel):
    paymentId: str
    paymentDate: datetime
    paymentMethod: PaymentMethod
    transactionReference: str
    status: PaymentStatus = PaymentStatus.PENDING
    amountPaid: Optional[float] = None
    balance: Optional[float] = None
    paymentProofUrl: Optional[str] = None
    history: List[PaymentTransaction] = []

    @validator('paymentMethod', pre=True)
    def validate_payment_method_case(cls, v):
        if isinstance(v, str):
            if v.lower() == 'bank transfer':
                return 'Bank Transfer'
            if v.lower() == 'cash':
                return 'Cash'
            if v.lower() == 'upi':
                return 'UPI'
            if v.lower() == 'cheque':
                return 'Cheque'
        return v

class CollectionCreate(BaseModel):
    fboId: str
    tripId: Optional[str] = None
    quantityCollected: float
    qualityGrade: QualityGrade
    qualityNotes: Optional[str] = None
    containerType: Optional[ContainerType] = None
    containerCount: Optional[int] = None
    containerIds: Optional[List[str]] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class Collection(CollectionCreate):
    collectionId: str
    fboName: str
    collectorId: str
    collectorName: str
    collectionDate: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pricePerKg: Optional[float] = None
    totalAmount: Optional[float] = None
    images: Optional[List[CollectionImage]] = []
    location: Optional[CollectionLocation] = None
    id: Optional[str] = None
    status: CollectionStatus = CollectionStatus.PENDING
    approvedBy: Optional[str] = None
    approvedAt: Optional[datetime] = None
    paymentDetails: Optional[PaymentDetails] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

class CollectionReview(BaseModel):
    action: str  # approve | reject
    qualityGrade: Optional[QualityGrade] = None
    pricePerKg: Optional[float] = None
    notes: Optional[str] = None

# Trip Models
class TripPlannedFBO(BaseModel):
    fboId: str
    fboName: str
    address: str
    estimatedQuantity: float
    sequence: int

class TripCompletedCollection(BaseModel):
    collectionId: str
    fboId: str
    quantityCollected: float
    amount: Optional[float] = 0.0
    completedAt: datetime

class TripCreate(BaseModel):
    vehicleNumber: str
    startOdometer: float
    plannedFBOs: List[TripPlannedFBO]

class Trip(TripCreate):
    tripId: str
    collectorId: str
    collectorName: str
    tripDate: datetime = Field(default_factory=datetime.utcnow)
    startTime: datetime = Field(default_factory=datetime.utcnow)
    endTime: Optional[datetime] = None
    endOdometer: Optional[float] = None
    totalKmTraveled: Optional[float] = None
    completedCollections: List[TripCompletedCollection] = []
    id: Optional[str] = None
    totalQuantityCollected: float = 0.0
    totalAmountCollected: float = 0.0
    status: TripStatus = TripStatus.PLANNED
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

class TripEnd(BaseModel):
    endOdometer: float
    notes: Optional[str] = None

# Payment Models
class PaymentBillingPeriod(BaseModel):
    startDate: datetime
    endDate: datetime

class PaymentDeduction(BaseModel):
    type: str
    amount: float
    reason: str

class PaymentCreate(BaseModel):
    fboId: str
    billingPeriod: PaymentBillingPeriod
    collectionIds: List[str]
    paymentMethod: PaymentMethod
    deductions: Optional[List[PaymentDeduction]] = None
    notes: Optional[str] = None

    @validator('paymentMethod', pre=True)
    def validate_payment_method_case(cls, v):
        if isinstance(v, str):
            if v.lower() == 'bank transfer':
                return 'Bank Transfer'
            if v.lower() == 'cash':
                return 'Cash'
            if v.lower() == 'upi':
                return 'UPI'
            if v.lower() == 'cheque':
                return 'Cheque'
        return v

class Payment(PaymentCreate):
    paymentId: str
    fboName: str
    totalQuantity: float
    averagePricePerKg: float
    totalAmount: float
    netAmount: float
    transactionReference: Optional[str] = None
    paymentDate: Optional[datetime] = None
    bankDetails: Optional[FBOBankDetails] = None
    id: Optional[str] = None
    status: PaymentStatus = PaymentStatus.PENDING
    processedBy: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

class PaymentUpdate(BaseModel):
    status: PaymentStatus
    transactionReference: Optional[str] = None
    notes: Optional[str] = None

# Pricing Models
class PricingCreate(BaseModel):
    qualityGrade: QualityGrade
    pricePerKg: float
    effectiveFrom: datetime
    effectiveTo: Optional[datetime] = None
    description: str
    criteria: str

class Pricing(PricingCreate):
    pricingId: str
    id: Optional[str] = None
    status: Status = Status.ACTIVE
    createdBy: str
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

# Notification Models
class NotificationData(BaseModel):
    collectionId: Optional[str] = None
    amount: Optional[float] = None

class NotificationCreate(BaseModel):
    type: NotificationType
    title: str
    message: str
    data: Optional[NotificationData] = None

class Notification(NotificationCreate):
    notificationId: str
    userId: str
    id: Optional[str] = None
    isRead: bool = False
    readAt: Optional[datetime] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)

# Setting Models (not used in endpoints but included)
class SettingCreate(BaseModel):
    settingKey: str
    settingValue: Any
    description: Optional[str] = None
    dataType: Optional[str] = "string"
    category: Optional[str] = "general"

class Setting(SettingCreate):
    id: Optional[str] = None
    updatedBy: str
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

# Support Models
class SupportMessageCreate(BaseModel):
    subject: str
    message: str

class SupportMessage(SupportMessageCreate):
    ticketId: str
    userId: str
    fboId: str
    status: str = "open"  # open, closed, in_progress
    createdAt: datetime = Field(default_factory=datetime.utcnow)

# Bill Models
class BillCollection(BaseModel):
    id: str  # collectionId
    date: datetime
    volume: float
    quality: str
    rate: float
    amount: float
    paid: float
    balance: float

class BillCreate(BaseModel):
    billNumber: str
    billDate: datetime
    fboId: str
    fboName: str
    fboAddress: Optional[str] = None
    dateFrom: str
    dateTo: str
    collections: List[BillCollection]
    totalVolume: float
    totalAmount: float
    totalPaid: float
    totalBalance: float
    companySettings: Optional[Dict[str, Any]] = None
    status: str = "generated"

class Bill(BillCreate):
    billId: str
    id: Optional[str] = None
    createdBy: Optional[str] = None
    createdByName: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)
    resolvedAt: Optional[datetime] = None
    response: Optional[str] = None
    resolvedAt: Optional[datetime] = None

# Item Master Models
class ItemMasterCreate(BaseModel):
    name: str
    description: Optional[str] = None

class ItemMaster(ItemMasterCreate):
    itemId: str
    id: Optional[str] = None
    createdBy: str
    createdByName: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
