"""
FastAPI dependencies for authentication.

Usage in route handlers:
    from app.api.deps import get_current_farmer_id

    @router.get("/me")
    async def me(farmer_id: str = Depends(get_current_farmer_id)):
        ...
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token

_bearer = HTTPBearer(auto_error=True)


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
