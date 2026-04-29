from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, Float, String
from sqlalchemy.orm import declarative_base, sessionmaker
import uuid
import logging
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI(title="Payment Service")

DATABASE_URL = "sqlite:///./payment_service.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

payments_failed_total = Counter(
    "payments_failed_total_payment_service",
    "Total failed payments in Payment Service"
)

logger = logging.getLogger("payment-service")
logger.setLevel(logging.INFO)

log_handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s %(correlation_id)s"
)
log_handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(log_handler)


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


def get_correlation_id(request: Request):
    return request.headers.get("X-Correlation-ID", str(uuid.uuid4()))


@app.get("/health")
def health():
    return {"service": "payment-service", "status": "UP"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/v1/payments")
def get_payments(request: Request):
    correlation_id = get_correlation_id(request)

    logger.info(
        "Fetching payments",
        extra={"correlation_id": correlation_id}
    )

    db = SessionLocal()
    payments = db.query(Payment).all()
    db.close()
    return payments


@app.post("/v1/payments/charge")
def charge_payment(
    request_data: PaymentRequest,
    request: Request,
    idempotency_key: str = Header(None)
):
    correlation_id = get_correlation_id(request)

    logger.info(
        "Payment charge request received",
        extra={"correlation_id": correlation_id}
    )

    if not idempotency_key:
        payments_failed_total.inc()

        logger.error(
            "Idempotency-Key missing",
            extra={"correlation_id": correlation_id}
        )

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

        logger.info(
            "Duplicate payment request avoided",
            extra={"correlation_id": correlation_id}
        )

        return {
            "message": "Duplicate payment avoided using idempotency",
            "correlation_id": correlation_id,
            "payment": existing_payment
        }

    payment = Payment(
        trip_id=request_data.trip_id,
        amount=request_data.amount,
        payment_method=request_data.payment_method,
        status="SUCCESS",
        transaction_reference=str(uuid.uuid4()),
        idempotency_key=idempotency_key
    )

    db.add(payment)
    db.commit()
    db.refresh(payment)
    db.close()

    logger.info(
        "Payment processed successfully",
        extra={"correlation_id": correlation_id}
    )

    return {
        "message": "Payment processed successfully",
        "correlation_id": correlation_id,
        "payment": payment
    }


@app.post("/v1/payments/{payment_id}/refund")
def refund_payment(payment_id: int, request: Request):
    correlation_id = get_correlation_id(request)

    db = SessionLocal()
    payment = db.query(Payment).filter(Payment.id == payment_id).first()

    if not payment:
        db.close()

        logger.error(
            f"Payment {payment_id} not found",
            extra={"correlation_id": correlation_id}
        )

        raise HTTPException(status_code=404, detail="Payment not found")

    payment.status = "REFUNDED"

    db.commit()
    db.refresh(payment)
    db.close()

    logger.info(
        f"Payment {payment_id} refunded successfully",
        extra={"correlation_id": correlation_id}
    )

    return {
        "message": "Payment refunded successfully",
        "correlation_id": correlation_id,
        "payment": payment
    }