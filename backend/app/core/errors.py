from __future__ import annotations

from fastapi import HTTPException, status


class AppError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        super().__init__(status_code=status_code, detail={"code": code, "message": message, "details": details or {}})


def not_found(what: str = "Resource") -> AppError:
    return AppError(status.HTTP_404_NOT_FOUND, "not_found", f"{what} not found")


def forbidden(message: str = "You do not have permission to perform this action") -> AppError:
    return AppError(status.HTTP_403_FORBIDDEN, "forbidden", message)


def bad_request(message: str, code: str = "invalid_request", details: dict | None = None) -> AppError:
    return AppError(status.HTTP_400_BAD_REQUEST, code, message, details)


def conflict(message: str, code: str = "conflict", details: dict | None = None) -> AppError:
    return AppError(status.HTTP_409_CONFLICT, code, message, details)


def unauthorized(message: str = "Authentication required", code: str = "unauthenticated") -> AppError:
    return AppError(status.HTTP_401_UNAUTHORIZED, code, message)
