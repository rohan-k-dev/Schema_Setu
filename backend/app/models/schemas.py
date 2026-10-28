"""
DEPRECATED: This file has been replaced by:
    - app/models/profile.py (FarmerProfile)
    - app/models/scheme.py (Scheme, RecommendedScheme)
    - app/models/requests.py (ChatRequest, TTSRequest)
    - app/models/responses.py (ChatResponse, TTSResponse, HealthResponse)

Kept for backward compatibility. Use the new modules for all new code.
"""

# Re-export from new locations
from app.models.profile import FarmerProfile
from app.models.scheme import Scheme as SchemeSchema