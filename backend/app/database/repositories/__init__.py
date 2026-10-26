"""
Database repositories package.

Each repository encapsulates SQL for one domain entity.
SQL NEVER appears outside this package (except migrations/importer).
"""

from app.database.repositories.scheme_repository import SchemeRepository
from app.database.repositories.rule_repository import RuleRepository
from app.database.repositories.source_repository import SourceRepository
from app.database.repositories.document_repository import DocumentRepository
from app.database.repositories.application_repository import ApplicationRepository

__all__ = [
    "SchemeRepository",
    "RuleRepository",
    "SourceRepository",
    "DocumentRepository",
    "ApplicationRepository",
]
