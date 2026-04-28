# Local Inbound Channel API Specs

Base URL for local backend:

```text
http://localhost:8000
```

The frontend shows the same endpoint through the Vite origin, but partner systems
should call the backend API directly in local demos.

## Common Rules

All channels require:

```text
Content-Type: application/json
X-Idempotency-Key: <unique-event-id>
X-Timestamp: <unix-epoch-seconds>
X-Signature: hmac-sha256=<hex>
```

Signature:

```text
HMAC-SHA256(secret, "{timestamp}.{raw_body}") as lowercase hex
```

Accepted responses:

```text
202 Accepted
```

Common failures:

```text
401 invalid signature, missing API key, or replay window violation
404 channel is missing, inactive, or not PUBLISHED
409 duplicated X-Idempotency-Key for the same channel
413 payload exceeds max_payload_bytes
422 invalid JSON or payload does not match the channel contract
```

## Channel 1: Vendor A Price Webhook

Purpose: external partner pushes product price events.

```text
POST http://localhost:8000/v1/inbound/vendor_a_price_webhook
Secret env name: VENDOR_A_HMAC_SECRET
Local demo secret: local-vendor-a-secret
Kind: WEBHOOK
Domain: agri_price
Item path: items
Max payload: 10 MB
Rate limit setting: 60/min
Replay window: 300 sec
```

Required payload fields:

```text
event_id: string
vendor_code: string
captured_at: string
items: array
items[].product_name: string
items[].price: number
```

Sample payload:

```json
{
  "event_id": "vendor-a-20260428-0001",
  "vendor_code": "vendor_a",
  "captured_at": "2026-04-28T12:00:00+09:00",
  "items": [
    {
      "source_product_id": "A-APPLE-10KG",
      "product_name": "apple 10kg",
      "price": 32000,
      "unit": "box",
      "store_name": "A Mart Gangnam"
    }
  ]
}
```

## Channel 2: Local OCR Price Result

Purpose: OCR system pushes recognized price-table or receipt results.

```text
POST http://localhost:8000/v1/inbound/local_ocr_price_result
Secret env name: LOCAL_OCR_HMAC_SECRET
Local demo secret: local-ocr-secret
Kind: OCR_RESULT
Domain: agri_price
Item path: items
Max payload: 10 MB
Rate limit setting: 60/min
Replay window: 300 sec
```

Required payload fields:

```text
event_id: string
vendor_code: string
document_id: string
captured_at: string
items: array
items[].product_name: string
items[].price: number
items[].confidence: number
```

Sample payload:

```json
{
  "event_id": "ocr-20260428-0001",
  "vendor_code": "local_ocr",
  "document_id": "receipt-001",
  "captured_at": "2026-04-28T12:00:00+09:00",
  "items": [
    {
      "product_name": "apple 10kg",
      "price": 32000,
      "unit": "box",
      "store_name": "A Mart Gangnam",
      "confidence": 0.93,
      "bbox": {
        "x": 120,
        "y": 88,
        "w": 220,
        "h": 42
      }
    }
  ]
}
```
