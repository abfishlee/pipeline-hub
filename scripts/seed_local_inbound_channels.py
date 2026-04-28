"""Seed local webhook and OCR inbound channels for agri_price demos."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from app.db.sync_session import get_sync_sessionmaker  # noqa: E402
from app.domain.inbound_contracts import upsert_contract  # noqa: E402


WEBHOOK_SCHEMA = {
    "type": "object",
    "required": ["event_id", "vendor_code", "captured_at", "items"],
    "properties": {
        "event_id": {"type": "string"},
        "vendor_code": {"type": "string"},
        "captured_at": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["product_name", "price"],
                "properties": {
                    "product_name": {"type": "string"},
                    "price": {"type": "number"},
                    "unit": {"type": "string"},
                    "store_name": {"type": "string"},
                    "source_product_id": {"type": "string"},
                },
            },
        },
    },
}

WEBHOOK_SAMPLE = {
    "event_id": "vendor-a-20260428-0001",
    "vendor_code": "vendor_a",
    "captured_at": "2026-04-28T12:00:00+09:00",
    "items": [
        {
            "source_product_id": "A-APPLE-10KG",
            "product_name": "apple 10kg",
            "price": 32000,
            "unit": "box",
            "store_name": "A Mart Gangnam",
        }
    ],
}

OCR_SCHEMA = {
    "type": "object",
    "required": ["event_id", "vendor_code", "captured_at", "document_id", "items"],
    "properties": {
        "event_id": {"type": "string"},
        "vendor_code": {"type": "string"},
        "document_id": {"type": "string"},
        "captured_at": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["product_name", "price", "confidence"],
                "properties": {
                    "product_name": {"type": "string"},
                    "price": {"type": "number"},
                    "unit": {"type": "string"},
                    "store_name": {"type": "string"},
                    "confidence": {"type": "number"},
                    "bbox": {"type": "object"},
                },
            },
        },
    },
}

OCR_SAMPLE = {
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
            "bbox": {"x": 120, "y": 88, "w": 220, "h": 42},
        }
    ],
}


def main() -> None:
    os.environ.setdefault("VENDOR_A_HMAC_SECRET", "local-vendor-a-secret")
    os.environ.setdefault("LOCAL_OCR_HMAC_SECRET", "local-ocr-secret")

    sm = get_sync_sessionmaker()
    with sm() as session:
        session.execute(
            text(
                """
                INSERT INTO domain.domain_definition
                    (domain_code, name, description, schema_yaml, status, version)
                VALUES
                    ('agri_price', '농수산물 가격정보',
                     'API, webhook, OCR 기반 농수산물 가격 데이터 도메인',
                     '{}'::jsonb, 'PUBLISHED', 1)
                ON CONFLICT (domain_code) DO NOTHING
                """
            )
        )
        channels = [
            {
                "channel_code": "vendor_a_price_webhook",
                "name": "Vendor A price webhook",
                "description": "Local demo webhook for partner price push payloads.",
                "channel_kind": "WEBHOOK",
                "secret_ref": "VENDOR_A_HMAC_SECRET",
                "schema": WEBHOOK_SCHEMA,
                "sample": WEBHOOK_SAMPLE,
                "notes": "Partner price push contract. Items array is the row path.",
            },
            {
                "channel_code": "local_ocr_price_result",
                "name": "Local OCR price result",
                "description": "Local demo OCR result push channel.",
                "channel_kind": "OCR_RESULT",
                "secret_ref": "LOCAL_OCR_HMAC_SECRET",
                "schema": OCR_SCHEMA,
                "sample": OCR_SAMPLE,
                "notes": "OCR result contract. Low confidence rows should go to review.",
            },
        ]
        for ch in channels:
            row = session.execute(
                text(
                    """
                    INSERT INTO domain.inbound_channel
                        (channel_code, domain_code, name, description, channel_kind,
                         secret_ref, auth_method, expected_content_type,
                         max_payload_bytes, rate_limit_per_min, replay_window_sec,
                         workflow_id, status, is_active)
                    VALUES
                        (:channel_code, 'agri_price', :name, :description,
                         :channel_kind, :secret_ref, 'hmac_sha256',
                         'application/json', 10485760, 60, 300, NULL,
                         'PUBLISHED', true)
                    ON CONFLICT (channel_code) DO UPDATE SET
                        domain_code = EXCLUDED.domain_code,
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        channel_kind = EXCLUDED.channel_kind,
                        secret_ref = EXCLUDED.secret_ref,
                        auth_method = EXCLUDED.auth_method,
                        expected_content_type = EXCLUDED.expected_content_type,
                        max_payload_bytes = EXCLUDED.max_payload_bytes,
                        rate_limit_per_min = EXCLUDED.rate_limit_per_min,
                        replay_window_sec = EXCLUDED.replay_window_sec,
                        status = 'PUBLISHED',
                        is_active = true,
                        updated_at = now()
                    RETURNING channel_id
                    """
                ),
                ch,
            ).first()
            upsert_contract(
                session,
                channel_code=ch["channel_code"],
                payload_schema=ch["schema"],
                sample_payload=ch["sample"],
                item_path="items",
                reject_on_schema_mismatch=True,
                notes=ch["notes"],
            )
            print(f"OK {ch['channel_code']} channel_id={row[0] if row else '?'}")
        session.commit()


if __name__ == "__main__":
    main()
