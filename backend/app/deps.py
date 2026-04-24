"""FastAPI dependency injection shared stubs.

Phase 1.2.3+ 에서 DB session / current_user / role guard 등으로 채워진다.
지금은 settings 만 제공.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


__all__ = ["SettingsDep"]
