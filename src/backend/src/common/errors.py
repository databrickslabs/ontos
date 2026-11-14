from typing import Any, Dict, Optional

from fastapi import HTTPException, status


class AppError(HTTPException):
    """Base exception for all application errors"""
    def __init__(
        self,
        status_code: int,
        detail: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)

class NotFoundError(AppError):
    """Raised when a requested resource is not found"""
    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

class ValidationError(AppError):
    """Raised when input validation fails. ``detail`` is a message, or a coded
    ``{code, message, params}`` dict the frontend translates."""
    def __init__(self, detail: Any = "Validation error") -> None:
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)

class ConflictError(AppError):
    """Raised when there's a conflict with existing data"""
    def __init__(self, detail: str = "Resource already exists") -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)

class UnauthorizedError(AppError):
    """Raised when user is not authorized"""
    def __init__(self, detail: str = "Unauthorized") -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)

class ForbiddenError(AppError):
    """Raised when user is forbidden from performing an action"""
    def __init__(self, detail: str = "Forbidden") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

class InternalServerError(AppError):
    """Raised when an unexpected error occurs"""
    def __init__(self, detail: str = "Internal server error") -> None:
        super().__init__(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)
