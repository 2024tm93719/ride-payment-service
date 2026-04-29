# Payment Service

The Payment Service securely handles trip fares, billing transactions, and payment statuses.

## Features
- Process card payments for completed trips.
- Process refunds for cancelled or disputed rides.
- Idempotency support to prevent duplicate charges.

## Tech Stack
- **Framework:** FastAPI
- **Database:** SQLite
- **ORM:** SQLAlchemy (Asynchronous)

## Running Locally

1. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the service:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8004
   ```

## Key Endpoints
- `POST /v1/payments/charge`: Charge a specific amount for a trip. Requires an `Idempotency-Key` header.
- `POST /v1/payments/{payment_id}/refund`: Issue a refund.
- `GET /v1/payments`: Retrieve all processed payments.
