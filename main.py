from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, Float, String
from sqlalchemy.orm import declarative_base, sessionmaker
import uuid

app = FastAPI(title="Payment Service")

DATABASE_URL = "sqlite:///./payment_service.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer)
    amount = Column(Float)
    payment_method = Column(String)
    status = Column(String)
    transaction_reference = Column(String)
    idempotency_key = Column(String, unique=True)


class PaymentRequest(BaseModel):
    trip_id: int
    amount: float
    payment_method: str = "CARD"


Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"service": "payment-service", "status": "UP"}


@app.get("/v1/payments")
def get_payments():
    db = SessionLocal()
    payments = db.query(Payment).all()
    db.close()
    return payments


@app.post("/v1/payments/charge")
def charge_payment(
    request: PaymentRequest,
    idempotency_key: str = Header(None)
):
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header is required"
        )

    db = SessionLocal()

    existing_payment = db.query(Payment).filter(
        Payment.idempotency_key == idempotency_key
    ).first()

    if existing_payment:
        db.close()
        return {
            "message": "Duplicate payment avoided using idempotency",
            "payment": existing_payment
        }

    payment = Payment(
        trip_id=request.trip_id,
        amount=request.amount,
        payment_method=request.payment_method,
        status="SUCCESS",
        transaction_reference=str(uuid.uuid4()),
        idempotency_key=idempotency_key
    )

    db.add(payment)
    db.commit()
    db.refresh(payment)
    db.close()

    return {
        "message": "Payment processed successfully",
        "payment": payment
    }


@app.post("/v1/payments/{payment_id}/refund")
def refund_payment(payment_id: int):
    db = SessionLocal()
    payment = db.query(Payment).filter(Payment.id == payment_id).first()

    if not payment:
        db.close()
        raise HTTPException(status_code=404, detail="Payment not found")

    payment.status = "REFUNDED"

    db.commit()
    db.refresh(payment)
    db.close()

    return {
        "message": "Payment refunded successfully",
        "payment": payment
    }