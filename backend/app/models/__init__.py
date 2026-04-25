"""SQLAlchemy ORM model registry.

각 스키마별 모델은 sub-module에 정의되며, Alembic env.py 가 import 가능하도록
이 파일에서 명시적으로 가져온다 (`autogenerate` 사용 시 필수).

Phase 1.2.3 진행 중 — 모델은 migration 파일과 1:1 로 추가됨.
"""

from __future__ import annotations

from app.models import audit as audit
from app.models import ctl as ctl
from app.models import mart as mart
from app.models import raw as raw
from app.models import run as run
from app.models import stg as stg
from app.models.base import Base

# Sub-module imports — Alembic target_metadata 가 모든 테이블을 인식.
# 향후 추가:
#   wf (Phase 3 Visual ETL), dq (Phase 2 데이터 품질) 등

__all__ = ["Base"]
