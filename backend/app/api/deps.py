"""
FastAPI dependencies for authentication.

Usage in route handlers:
    from app.api.deps import get_current_farmer_id

    @router.get("/me")
    async def me(farmer_id: str = Depends(get_current_farmer_id)):
        ...
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token

_bearer = HTTPBearer(auto_error=True)
_optional_bearer = HTTPBearer(auto_error=False)


async def get_current_farmer_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """
    Validate the Bearer JWT in the Authorization header.

    Returns the ``farmer_id`` (UUID string) on success.
    Raises HTTP 401 on any failure.
    """
    token = credentials.credentials
    farmer_id = decode_access_token(token)
    if not farmer_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return farmer_id


async def get_optional_farmer_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
) -> Optional[str]:
    """Return the authenticated farmer ID when a valid bearer token is supplied."""
    if credentials is None:
        return None

    farmer_id = decode_access_token(credentials.credentials)
    if not farmer_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return farmer_id
