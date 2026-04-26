"""HTTP — `/v2/service-mart` (Phase 8 — Service Mart Viewer endpoint).

4 가상 유통사 데이터를 통합한 service_mart.product_price 조회 + std_product 마스터.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.sync_session import get_sync_sessionmaker
from app.deps import require_roles

router = APIRouter(
    prefix="/v2/service-mart",
    tags=["v2-service-mart"],
    dependencies=[
        Depends(require_roles("ADMIN", "DOMAIN_ADMIN", "APPROVER", "OPERATOR"))
    ],
)


class StdProductOut(BaseModel):
    std_product_code: str
    std_product_name: str
    category: str | None
    unit_kind: str | None
    description: str | None


class ServicePriceRow(BaseModel):
    price_id: int
    std_product_code: str | None
    std_product_name: str | None
    retailer_code: str
    retailer_product_code: str
    product_name: str
    display_name: str | None
    price_normal: Decimal | None
    price_promo: Decimal | None
    promo_type: str | None
    promo_start: datetime | None
    promo_end: datetime | None
    stock_qty: int | None
    stock_status: str | None
    unit: str | None
    origin: str | None
    grade: str | None
    standardize_confidence: Decimal | None
    needs_review: bool
    collected_at: datetime


class ChannelStats(BaseModel):
    retailer_code: str
    row_count: int
    products_with_promo: int
    avg_confidence: Decimal | None
    needs_review_count: int


def _run_in_sync(fn: Any) -> Any:
    sm = get_sync_sessionmaker()
    with sm() as session:
        return fn(session)


@router.get("/std-products", response_model=list[StdProductOut])
async def list_std_products() -> list[StdProductOut]:
    def _do(s: Session) -> list[StdProductOut]:
        rows = s.execute(
            text(
                "SELECT std_product_code, std_product_name, category, "
                "       unit_kind, description "
                "FROM service_mart.std_product "
                "ORDER BY category, std_product_name"
            )
        ).all()
        return [
            StdProductOut(
                std_product_code=str(r.std_product_code),
                std_product_name=str(r.std_product_name),
                category=str(r.category) if r.category else None,
                unit_kind=str(r.unit_kind) if r.unit_kind else None,
                description=str(r.description) if r.description else None,
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/prices", response_model=list[ServicePriceRow])
async def list_service_prices(
    std_product_code: str | None = None,
    retailer_code: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[ServicePriceRow]:
    """4 유통사 통합 가격 조회. 표준 품목 / 유통사 별 필터링 가능."""

    def _do(s: Session) -> list[ServicePriceRow]:
        sql = (
            "SELECT p.price_id, p.std_product_code, sp.std_product_name, "
            "       p.retailer_code, p.retailer_product_code, p.product_name, "
            "       p.display_name, p.price_normal, p.price_promo, "
            "       p.promo_type, p.promo_start, p.promo_end, "
            "       p.stock_qty, p.stock_status, p.unit, p.origin, p.grade, "
            "       p.standardize_confidence, p.needs_review, p.collected_at "
            "FROM service_mart.product_price p "
            "LEFT JOIN service_mart.std_product sp "
            "  ON p.std_product_code = sp.std_product_code "
        )
        clauses: list[str] = []
        params: dict[str, Any] = {"lim": limit}
        if std_product_code:
            clauses.append("p.std_product_code = :spc")
            params["spc"] = std_product_code
        if retailer_code:
            clauses.append("p.retailer_code = :rc")
            params["rc"] = retailer_code
        if clauses:
            sql += "WHERE " + " AND ".join(clauses) + " "
        sql += "ORDER BY p.collected_at DESC LIMIT :lim"
        rows = s.execute(text(sql), params).all()
        return [
            ServicePriceRow(
                price_id=int(r.price_id),
                std_product_code=(
                    str(r.std_product_code) if r.std_product_code else None
                ),
                std_product_name=(
                    str(r.std_product_name) if r.std_product_name else None
                ),
                retailer_code=str(r.retailer_code),
                retailer_product_code=str(r.retailer_product_code),
                product_name=str(r.product_name),
                display_name=(
                    str(r.display_name) if r.display_name else None
                ),
                price_normal=r.price_normal,
                price_promo=r.price_promo,
                promo_type=str(r.promo_type) if r.promo_type else None,
                promo_start=r.promo_start,
                promo_end=r.promo_end,
                stock_qty=int(r.stock_qty) if r.stock_qty is not None else None,
                stock_status=(
                    str(r.stock_status) if r.stock_status else None
                ),
                unit=str(r.unit) if r.unit else None,
                origin=str(r.origin) if r.origin else None,
                grade=str(r.grade) if r.grade else None,
                standardize_confidence=r.standardize_confidence,
                needs_review=bool(r.needs_review),
                collected_at=r.collected_at,
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


@router.get("/channel-stats", response_model=list[ChannelStats])
async def list_channel_stats() -> list[ChannelStats]:
    """채널별 row 수 / 행사 비율 / 평균 confidence / 검수 큐 카운트."""

    def _do(s: Session) -> list[ChannelStats]:
        rows = s.execute(
            text(
                """
                SELECT retailer_code,
                       COUNT(*) AS row_count,
                       COUNT(*) FILTER (WHERE price_promo IS NOT NULL) AS promo_count,
                       AVG(standardize_confidence) AS avg_conf,
                       COUNT(*) FILTER (WHERE needs_review = true) AS review_count
                  FROM service_mart.product_price
                 GROUP BY retailer_code
                 ORDER BY retailer_code
                """
            )
        ).all()
        return [
            ChannelStats(
                retailer_code=str(r.retailer_code),
                row_count=int(r.row_count),
                products_with_promo=int(r.promo_count),
                avg_confidence=r.avg_conf,
                needs_review_count=int(r.review_count),
            )
            for r in rows
        ]

    return await asyncio.to_thread(_run_in_sync, _do)


__all__ = ["router"]
