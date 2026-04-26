"""Phase 8 — Synthetic 가상 데이터 시드.

4 가상 유통사 (이마트/홈플러스/롯데마트/하나로마트) 의 가격/행사/재고 데이터 +
표준 품목 마스터 + 서비스 통합 마트 데이터를 생성.

실행:
    cd backend
    .venv/Scripts/python ../scripts/phase8_seed_synthetic_data.py

생성:
  - service_mart.std_product (10종): 사과 / 배 / 양파 / 대파 / 한우불고기 / 등
  - emart_mart.product_price (12 rows): 정상 케이스 + 일부 오류
  - homeplus_mart.product_promo (10 rows): 행사 케이스 + 일부 역순 행사기간
  - lottemart_mart.product_canon (8 rows): 마케팅 문구 + 정규화 confidence
  - hanaro_mart.agri_product (10 rows): 산지/등급/단위
  - service_mart.product_price (40 rows): 4 유통사 통합

멱등성: 같은 retailer_product_code + collected_at 으로 두 번 실행해도 안전.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker

NOW = datetime.now(UTC)


# ============================================================================
# 1. 표준 품목 마스터 (service_mart.std_product)
# ============================================================================
STD_PRODUCTS = [
    ("FRT_APPLE", "사과", "fruit", "kg", "사과 (홍로/부사 등)"),
    ("FRT_PEAR", "배", "fruit", "kg", "신고 배"),
    ("FRT_GRAPE", "샤인머스캣", "fruit", "kg", "샤인머스캣"),
    ("VEG_ONION", "양파", "vegetable", "kg", "양파"),
    ("VEG_GREEN_ONION", "대파", "vegetable", "단", "대파"),
    ("VEG_TOMATO", "토마토", "vegetable", "kg", "완숙토마토"),
    ("VEG_RADISH", "무", "vegetable", "ea", "제주 무"),
    ("MEAT_BEEF", "한우 불고기", "meat", "g", "한우 불고기용"),
    ("MEAT_PORK", "돼지 삼겹살", "meat", "g", "돼지 삼겹살"),
    ("EGG_FRESH", "신선란", "egg", "ea", "30구 계란"),
]


# ============================================================================
# 2. 이마트 — 표준 API 성공 + 일부 오류
# ============================================================================
EMART_DATA = [
    # (product_code, product_name, price, discount_price, stock_qty, std_code)
    ("EM-APL-001", "당도선별 사과 1.5kg", 12900, 10900, 42, "FRT_APPLE"),
    ("EM-APL-002", "GAP 인증 사과 2kg", 18900, None, 28, "FRT_APPLE"),
    ("EM-PER-010", "신고 배 3입", 9900, 7900, 35, "FRT_PEAR"),
    ("EM-ONI-021", "국내산 양파 2kg", 5980, 4980, 67, "VEG_ONION"),
    ("EM-GON-030", "국내산 대파 1단", 2490, 2290, 89, "VEG_GREEN_ONION"),
    ("EM-TOM-040", "완숙토마토 1kg", 6990, None, 45, "VEG_TOMATO"),
    ("EM-BEF-112", "한우 불고기 600g", 24800, 21900, 18, "MEAT_BEEF"),
    ("EM-PRK-130", "한돈 삼겹살 600g", 17900, 15900, 22, "MEAT_PORK"),
    ("EM-EGG-030", "신선란 30구", 8990, None, 73, "EGG_FRESH"),
    # 의도적 오류
    ("EM-ERR-001", "오류 케이스 — price 누락", None, None, 10, None),  # price NULL
    ("EM-ERR-002", "오류 케이스 — 재고 음수", 5000, None, -3, None),  # stock 음수
    ("EM-ERR-003", "오류 케이스 — 가격 0", 0, None, 50, None),  # price 0
]


# ============================================================================
# 3. 홈플러스 — 행사/할인
# ============================================================================
HOMEPLUS_DATA = [
    # (item_id, item_title, sale_price, promo_type, promo_start, promo_end, std_code)
    ("HP-10031", "국내산 양파 2kg", 5980, "CARD_DISCOUNT", "2026-05-01", "2026-05-07", "VEG_ONION"),
    ("HP-20088", "제주 무 1입", 1980, "ONE_PLUS_ONE", "2026-05-01", "2026-05-03", "VEG_RADISH"),
    ("HP-33010", "완숙토마토 1kg", 6990, "NONE", None, None, "VEG_TOMATO"),
    ("HP-44020", "신고 배 3입", 8900, "PERIOD_DISCOUNT", "2026-04-25", "2026-05-10", "FRT_PEAR"),
    ("HP-55030", "샤인머스캣 1kg", 19900, "CARD_DISCOUNT", "2026-05-01", "2026-05-31", "FRT_GRAPE"),
    ("HP-66040", "한돈 삼겹살 800g", 22900, "ONE_PLUS_ONE", "2026-05-01", "2026-05-02", "MEAT_PORK"),
    ("HP-77050", "신선란 30구", 7990, "PERIOD_DISCOUNT", "2026-04-26", "2026-05-03", "EGG_FRESH"),
    # 의도적 오류
    ("HP-ERR-001", "오류 — 행사 종료가 시작보다 빠름", 5000, "PERIOD_DISCOUNT",
     "2026-05-10", "2026-05-01", None),
    ("HP-ERR-002", "오류 — 알 수 없는 promo_type", 3000, "INVALID_PROMO", "2026-05-01", "2026-05-07", None),
    ("HP-ERR-003", "오류 — sale_price 만 있고 promo_type 없음", 2000, None, None, None, None),
]


# ============================================================================
# 4. 롯데마트 — 상품명 정규화 난이도
# ============================================================================
LOTTEMART_DATA = [
    # (goods_no, display_name, cleaned, extracted_size, amt, unit, confidence, std_code)
    ("LM-778812", "[행사] GAP 인증 충주 사과 봉지 1.8kg", "GAP 인증 충주 사과", "1.8kg", 11900, "봉", 0.92, "FRT_APPLE"),
    ("LM-881920", "오늘만 특가! 국내산 대파 1단", "국내산 대파", "1단", 2490, "단", 0.88, "VEG_GREEN_ONION"),
    ("LM-331120", "프리미엄 한돈 삼겹살 구이용 500g", "한돈 삼겹살 구이용", "500g", 13900, "팩", 0.85, "MEAT_PORK"),
    ("LM-441230", "[1+1] 국산 햇사과 봉지 2kg", "국산 햇사과", "2kg", 14900, "봉", 0.90, "FRT_APPLE"),
    ("LM-551340", "한정수량! 제주 무 1입", "제주 무", "1입", 1980, "ea", 0.83, "VEG_RADISH"),
    # 의도적 오류 — confidence 낮음
    ("LM-LOW-001", "프리미엄 빨간 과일 봉지 한정수량 특가", "빨간 과일 봉지", None, 8900, None, 0.62, None),
    ("LM-LOW-002", "오늘만 행사 신상 채소 묶음", "채소 묶음", None, 6900, None, 0.58, None),
    ("LM-LOW-003", "당일 배송 한우 갈비 모음", "한우 갈비", "?", 35000, "팩", 0.71, None),
]


# ============================================================================
# 5. 하나로마트 — 농축수산물 산지/등급/단위
# ============================================================================
HANARO_DATA = [
    # (product_cd, name, origin, grade, unit, price, std_code)
    ("NH-AP-001", "홍로 사과", "충북 충주", "특", "10kg", 48900, "FRT_APPLE"),
    ("NH-AP-002", "부사 사과", "경북 영주", "상", "5kg", 28900, "FRT_APPLE"),
    ("NH-PE-010", "신고 배", "전남 나주", "특", "7.5kg", 38900, "FRT_PEAR"),
    ("NH-GR-020", "샤인머스캣", "경북 김천", "상", "2kg", 29900, "FRT_GRAPE"),
    ("NH-ON-030", "양파", "전남 무안", "1등급", "20kg", 24900, "VEG_ONION"),
    ("NH-GO-040", "대파", "전남 진도", "1등급", "5kg", 8900, "VEG_GREEN_ONION"),
    ("NH-PK-115", "돼지 앞다리살", "국내산", "1등급", "600g", 7900, "MEAT_PORK"),
    ("NH-BF-201", "한우 등심", "국내산", "1++등급", "300g", 24900, "MEAT_BEEF"),
    # 의도적 오류
    ("NH-ERR-001", "오류 — 산지 누락", None, "특", "5kg", 12900, None),
    ("NH-ERR-002", "오류 — 등급 비표준", "국내산", "프리미엄+++", "1kg", 9900, None),
]


def seed_std_products(session) -> int:
    inserted = 0
    for std_code, name, category, unit, desc in STD_PRODUCTS:
        result = session.execute(
            text(
                "INSERT INTO service_mart.std_product "
                "(std_product_code, std_product_name, category, unit_kind, description) "
                "VALUES (:c, :n, :cat, :u, :d) "
                "ON CONFLICT (std_product_code) DO NOTHING"
            ),
            {"c": std_code, "n": name, "cat": category, "u": unit, "d": desc},
        )
        inserted += result.rowcount or 0
    print(f"[std_product] inserted={inserted} (10 total)".encode("ascii", "replace").decode())
    return inserted


def seed_emart(session) -> int:
    count = 0
    for code, name, price, dprice, qty, std_code in EMART_DATA:
        ts = NOW - timedelta(minutes=random.randint(0, 60))
        # emart_mart.product_price
        session.execute(
            text(
                "INSERT INTO emart_mart.product_price "
                "(retailer_product_code, product_name, price, discount_price, "
                " stock_qty, collected_at) "
                "VALUES (:rc, :n, :p, :dp, :q, :ts)"
            ),
            {
                "rc": code,
                "n": name,
                "p": price,
                "dp": dprice,
                "q": qty,
                "ts": ts,
            },
        )
        # service_mart.product_price (정상 케이스만)
        if std_code and price and (qty is None or qty >= 0):
            stock_status = (
                "OUT_OF_STOCK"
                if qty == 0
                else "IN_STOCK"
                if qty and qty > 0
                else "UNKNOWN"
            )
            session.execute(
                text(
                    "INSERT INTO service_mart.product_price "
                    "(std_product_code, retailer_code, retailer_product_code, "
                    " product_name, price_normal, price_promo, stock_qty, "
                    " stock_status, standardize_confidence, collected_at) "
                    "VALUES (:s, 'emart', :rc, :n, :p, :dp, :q, :ss, 0.95, :ts) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "s": std_code,
                    "rc": code,
                    "n": name,
                    "p": price,
                    "dp": dprice,
                    "q": qty,
                    "ss": stock_status,
                    "ts": ts,
                },
            )
        count += 1
    print(f"[emart] inserted={count} retailer rows + service_mart")
    return count


def seed_homeplus(session) -> int:
    count = 0
    for item in HOMEPLUS_DATA:
        item_id, title, sale_price, promo_type, ps, pe, std_code = item
        ts = NOW - timedelta(minutes=random.randint(0, 60))
        session.execute(
            text(
                "INSERT INTO homeplus_mart.product_promo "
                "(item_id, item_title, sale_price, promo_type, "
                " promo_start, promo_end, collected_at) "
                "VALUES (:i, :t, :sp, :pt, "
                "        CAST(:ps AS DATE), CAST(:pe AS DATE), :ts)"
            ),
            {
                "i": item_id,
                "t": title,
                "sp": sale_price,
                "pt": promo_type,
                "ps": ps,
                "pe": pe,
                "ts": ts,
            },
        )
        # service_mart — 정상 case
        if std_code and sale_price and promo_type in (
            "CARD_DISCOUNT",
            "ONE_PLUS_ONE",
            "PERIOD_DISCOUNT",
            "NONE",
        ):
            normal = (
                int(Decimal(sale_price) / Decimal("0.85"))
                if promo_type != "NONE"
                else sale_price
            )
            session.execute(
                text(
                    "INSERT INTO service_mart.product_price "
                    "(std_product_code, retailer_code, retailer_product_code, "
                    " product_name, price_normal, price_promo, "
                    " promo_type, promo_start, promo_end, stock_status, "
                    " standardize_confidence, collected_at) "
                    "VALUES (:s, 'homeplus', :rc, :n, :pn, :pp, :pt, "
                    "        CAST(:ps AS TIMESTAMPTZ), CAST(:pe AS TIMESTAMPTZ), "
                    "        'IN_STOCK', 0.91, :ts) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "s": std_code,
                    "rc": item_id,
                    "n": title,
                    "pn": normal,
                    "pp": sale_price,
                    "pt": promo_type if promo_type != "NONE" else None,
                    "ps": ps,
                    "pe": pe,
                    "ts": ts,
                },
            )
        count += 1
    print(f"[homeplus] inserted={count} retailer rows + service_mart")
    return count


def seed_lottemart(session) -> int:
    count = 0
    for item in LOTTEMART_DATA:
        goods_no, display_name, cleaned, size, amt, unit, conf, std_code = item
        ts = NOW - timedelta(minutes=random.randint(0, 60))
        session.execute(
            text(
                "INSERT INTO lottemart_mart.product_canon "
                "(goods_no, display_name, cleaned_name, extracted_size, "
                " current_amt, unit_text, standardize_confidence, collected_at) "
                "VALUES (:gn, :dn, :cn, :sz, :amt, :ut, :cf, :ts)"
            ),
            {
                "gn": goods_no,
                "dn": display_name,
                "cn": cleaned,
                "sz": size,
                "amt": amt,
                "ut": unit,
                "cf": conf,
                "ts": ts,
            },
        )
        # service_mart — confidence ≥ 0.75 만 적재 (검수 큐 정책)
        if std_code and conf >= 0.75:
            session.execute(
                text(
                    "INSERT INTO service_mart.product_price "
                    "(std_product_code, retailer_code, retailer_product_code, "
                    " product_name, display_name, price_normal, unit, "
                    " stock_status, standardize_confidence, "
                    " needs_review, collected_at) "
                    "VALUES (:s, 'lottemart', :rc, :n, :dn, :p, :u, "
                    "        'IN_STOCK', :cf, :nr, :ts) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "s": std_code,
                    "rc": goods_no,
                    "n": cleaned,
                    "dn": display_name,
                    "p": amt,
                    "u": size or unit,
                    "cf": conf,
                    "nr": conf < 0.85,
                    "ts": ts,
                },
            )
        count += 1
    print(f"[lottemart] inserted={count} retailer rows + service_mart")
    return count


def seed_hanaro(session) -> int:
    count = 0
    for item in HANARO_DATA:
        product_cd, name, origin, grade, unit, price, std_code = item
        # 단위 변환 — kg 당 가격
        price_per_kg = None
        if price and unit:
            if "kg" in unit:
                try:
                    kg = float(unit.replace("kg", "").strip())
                    price_per_kg = float(price) / kg if kg > 0 else None
                except ValueError:
                    pass
            elif "g" in unit:
                try:
                    g = float(unit.replace("g", "").strip())
                    price_per_kg = float(price) / (g / 1000) if g > 0 else None
                except ValueError:
                    pass
        ts = NOW - timedelta(minutes=random.randint(0, 60))
        session.execute(
            text(
                "INSERT INTO hanaro_mart.agri_product "
                "(product_cd, name, origin, grade, unit, price, "
                " price_per_kg, collected_at) "
                "VALUES (:c, :n, :o, :g, :u, :p, :ppkg, :ts)"
            ),
            {
                "c": product_cd,
                "n": name,
                "o": origin,
                "g": grade,
                "u": unit,
                "p": price,
                "ppkg": price_per_kg,
                "ts": ts,
            },
        )
        # service_mart — 정상 case
        if std_code:
            session.execute(
                text(
                    "INSERT INTO service_mart.product_price "
                    "(std_product_code, retailer_code, retailer_product_code, "
                    " product_name, price_normal, unit, origin, grade, "
                    " stock_status, standardize_confidence, collected_at) "
                    "VALUES (:s, 'hanaro', :rc, :n, :p, :u, :o, :g, "
                    "        'IN_STOCK', 0.93, :ts) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "s": std_code,
                    "rc": product_cd,
                    "n": name,
                    "p": price,
                    "u": unit,
                    "o": origin,
                    "g": grade,
                    "ts": ts,
                },
            )
        count += 1
    print(f"[hanaro] inserted={count} retailer rows + service_mart")
    return count


def main() -> int:
    import sys
    # Windows 콘솔 cp949 → utf-8 강제
    if sys.stdout.encoding and "utf" not in sys.stdout.encoding.lower():
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
    sm = get_sync_sessionmaker()
    print("=" * 70)
    print("Phase 8 - Synthetic Data Seed (4 retailers x synthetic data)")
    print("=" * 70)
    try:
        with sm() as session:
            seed_std_products(session)
            seed_emart(session)
            seed_homeplus(session)
            seed_lottemart(session)
            seed_hanaro(session)
            session.commit()
        print("\n[done] 가상 데이터 시드 완료.")
        print("  - service_mart.std_product: 10")
        print("  - emart_mart.product_price: 12 (정상 9 + 오류 3)")
        print("  - homeplus_mart.product_promo: 10 (정상 7 + 오류 3)")
        print("  - lottemart_mart.product_canon: 8 (정상 5 + low conf 3)")
        print("  - hanaro_mart.agri_product: 10 (정상 8 + 오류 2)")
        print("  - service_mart.product_price: ~30+ (정상 케이스만)")
        print("\n다음:")
        print("  → 화면에서 /v2/service-mart 또는 Operations Dashboard 확인")
    finally:
        dispose_sync_engine()
    return 0


if __name__ == "__main__":
    main()
