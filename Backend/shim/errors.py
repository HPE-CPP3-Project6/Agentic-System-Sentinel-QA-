from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def api_error(status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error": {"code": code, "message": message, "detail": detail or {}}},
    )
