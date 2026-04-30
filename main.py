from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import Column, Integer, Float, String, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
import uuid
import logging
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI(title="Payment Service")

DATABASE_URL = "sqlite+aiosqlite:///./payment_service.db"

engine = create_async_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
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


class PaymentResponse(BaseModel):
    id: int
    trip_id: int
    amount: float
    payment_method: str
    status: str
    transaction_reference: str
    idempotency_key: str

    class Config:
        from_attributes = True


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with SessionLocal() as session:
        yield session


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    import uuid
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.on_event("startup")
async def startup_event():
    await init_db()


@app.get("/health")
def health():
    return {"service": "payment-service", "status": "UP"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/v1/payments", response_model=list[PaymentResponse])
async def get_payments(request: Request, db: AsyncSession = Depends(get_db)):
    correlation_id = request.state.correlation_id

    logger.info(
        "Fetching payments",
        extra={"correlation_id": correlation_id}
    )

    result = await db.execute(select(Payment))
    return result.scalars().all()


@app.post("/v1/payments/charge")
async def charge_payment(
    request_data: PaymentRequest,
    request: Request,
    idempotency_key: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    correlation_id = request.state.correlation_id

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

    result = await db.execute(
        select(Payment).filter(Payment.idempotency_key == idempotency_key)
    )
    existing_payment = result.scalars().first()

    if existing_payment:
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
    await db.commit()
    await db.refresh(payment)

    logger.info(
        "Payment processed successfully",
        extra={"correlation_id": correlation_id}
    )

    return {
        "message": "Payment processed successfully",
        "correlation_id": correlation_id,
        "payment": payment
    }


@app.post("/v1/payments/{payment_id}/refund", response_model=PaymentResponse)
async def refund_payment(payment_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    correlation_id = request.state.correlation_id

    result = await db.execute(select(Payment).filter(Payment.id == payment_id))
    payment = result.scalars().first()

    if not payment:
        logger.error(
            f"Payment {payment_id} not found",
            extra={"correlation_id": correlation_id}
        )
        raise HTTPException(status_code=404, detail="Payment not found")

    payment.status = "REFUNDED"

    await db.commit()
    await db.refresh(payment)

    logger.info(
        f"Payment {payment_id} refunded successfully",
        extra={"correlation_id": correlation_id}
    )

    return payment