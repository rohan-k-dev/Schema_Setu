"""
Role-based access control — the permission matrix (docs/RBAC.md).

Deny by default: a principal may do something only if its role's permission set
contains the permission. Unknown roles and unknown permissions get nothing.

Every check is made on the server: in the FastAPI dependency of each route
(app.api.deps.require / require_own) and again in the service functions that act
for staff (review and administration). Hiding a button in the frontend is never
the protection.

Scope (who the permission applies to) is part of each permission:
  *_OWN       only the signed-in account's own data — the account always comes from
              the session; no request can name another account.
  REVIEW_*    the human-review queue (anonymised cases, Aadhaar etc. stripped).
  SCHEME_*    curation flags of the scheme corpus (status / needs-review), never rules.
  USER_*      account administration: account metadata only (no profiles, no saved
              schemes, no search history, no phone numbers).
  AUDIT_READ  the append-only audit log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Optional


class Role(str, Enum):
    FARMER = "FARMER"            # every new account
    REVIEWER = "REVIEWER"        # human-review staff
    ADMIN = "ADMIN"              # account administration, scheme curation, audit


class Permission(str, Enum):
    PROFILE_OWN_READ = "profile:own:read"
    PROFILE_OWN_WRITE = "profile:own:write"
    SAVED_SCHEMES_OWN_READ = "saved_schemes:own:read"
    SAVED_SCHEMES_OWN_WRITE = "saved_schemes:own:write"
    HISTORY_OWN_READ = "search_history:own:read"
    HISTORY_OWN_DELETE = "search_history:own:delete"
    ELIGIBILITY_OWN_READ = "eligibility:own:read"
    REVIEW_OWN_READ = "review_cases:own:read"      # status of review cases your own searches raised
    ACCOUNT_OWN_DATA = "account:own:data"         # see / export / delete your own account data (docs/PRIVACY.md)
    REVIEW_CASE_READ = "review_cases:read"
    REVIEW_CASE_DECIDE = "review_cases:decide"
    REVIEW_CASE_ASSIGN = "review_cases:assign"       # assign / reassign cases to reviewers (docs/HUMAN_REVIEW.md)
    SCHEME_CURATE = "schemes:curate"
    USER_READ = "users:read"
    USER_ROLE_ASSIGN = "users:role:assign"
    USER_STATUS_MANAGE = "users:status:manage"
    REVIEWER_APPROVE = "users:reviewer:approve"   # approve / revoke reviewer accounts (docs/HUMAN_REVIEW.md)
    AUDIT_READ = "audit:read"
    # Operations dashboard (docs/ADMIN_OPERATIONS.md)
    OPS_READ = "ops:read"                    # health, corpus, jobs, graph sync, reviews, errors, conflicts
    OPS_VALIDATE = "ops:validate"            # run the read-only data validation
    OPS_RUN_JOBS = "ops:jobs:run"            # start ingestion / graph-rebuild jobs
    # Scheme updates & notifications (docs/SCHEME_UPDATES.md)
    NOTIFICATIONS_OWN = "notifications:own"  # own inbox, preferences, subscriptions, phone
    CHAT_HISTORY_OWN = "chat_history:own"    # own saved conversations: list, open, continue, delete (docs/CHAT_HISTORY.md)
    SCHEME_CHANGES_REVIEW = "scheme_changes:review"   # detect, approve / reject, discard
    NOTIFICATIONS_ADMIN = "notifications:admin"       # delivery status, dispatch retries


_OWN_DATA = frozenset({
    Permission.PROFILE_OWN_READ, Permission.PROFILE_OWN_WRITE,
    Permission.SAVED_SCHEMES_OWN_READ, Permission.SAVED_SCHEMES_OWN_WRITE,
    Permission.HISTORY_OWN_READ, Permission.HISTORY_OWN_DELETE,
    Permission.ELIGIBILITY_OWN_READ, Permission.NOTIFICATIONS_OWN, Permission.REVIEW_OWN_READ,
    Permission.CHAT_HISTORY_OWN,
    Permission.ACCOUNT_OWN_DATA,
})

# The matrix. Own-data permissions are scoped to the account itself, so giving them to
# staff accounts grants no access to anyone else's data.
ROLE_PERMISSIONS: dict[Role, FrozenSet[Permission]] = {
    Role.FARMER: _OWN_DATA,
    Role.REVIEWER: _OWN_DATA | {Permission.REVIEW_CASE_READ, Permission.REVIEW_CASE_DECIDE},
    # Administrators oversee the review queue (read) but do not decide cases
    # (separation of duties): a decision needs a reviewer.
    Role.ADMIN: _OWN_DATA | {
        Permission.REVIEW_CASE_READ, Permission.REVIEW_CASE_ASSIGN,
        Permission.SCHEME_CURATE,
        Permission.USER_READ, Permission.USER_ROLE_ASSIGN, Permission.USER_STATUS_MANAGE, Permission.REVIEWER_APPROVE,
        Permission.AUDIT_READ,
        Permission.OPS_READ, Permission.OPS_VALIDATE, Permission.OPS_RUN_JOBS,
        Permission.SCHEME_CHANGES_REVIEW, Permission.NOTIFICATIONS_ADMIN,
    },
}

# What only an APPROVED reviewer gets (the REVIEWER role without approval has own data only).
REVIEWER_STAFF_PERMISSIONS: FrozenSet[Permission] = frozenset(
    {Permission.REVIEW_CASE_READ, Permission.REVIEW_CASE_DECIDE})

# The development-only shared reviewer key (X-Review-Key) acts for no account: it may
# read and decide review cases, nothing else — never any *_OWN or administrator permission.
REVIEW_KEY_PERMISSIONS: FrozenSet[Permission] = frozenset(
    {Permission.REVIEW_CASE_READ, Permission.REVIEW_CASE_DECIDE})


def permissions_for(role: object) -> FrozenSet[Permission]:
    """The role's permissions; an unknown or missing role has none (deny by default)."""
    try:
        return ROLE_PERMISSIONS.get(Role(role), frozenset())
    except ValueError:
        return frozenset()


@dataclass(frozen=True)
class Principal:
    """Who is making the request, as established by the server (never by the client)."""

    role: Optional[Role]
    label: str                                   # e-mail, or "review-key" (audit actor)
    account_pk: Optional[int] = None             # farmers.id; None for the review key
    farmer_id: Optional[str] = None              # public account UUID
    via: str = "session"                         # "session" / "review_key"
    ip_address: Optional[str] = None
    permissions: FrozenSet[Permission] = field(default=frozenset())

    @classmethod
    def for_account(cls, account, ip_address: Optional[str] = None) -> "Principal":
        role = Role(account.role) if account.role in Role._value2member_map_ else None
        perms = permissions_for(account.role)
        # Reviewer policy (docs/HUMAN_REVIEW.md): the REVIEWER role alone grants nothing beyond
        # own data until an administrator has approved the account; rebuilt on every request,
        # so approval and revocation apply immediately.
        if role == Role.REVIEWER and not getattr(account, "reviewer_approved_at", None):
            perms = perms - REVIEWER_STAFF_PERMISSIONS
        return cls(role=role, label=account.email, account_pk=account.id, farmer_id=account.farmer_id,
                   ip_address=ip_address, permissions=perms)

    @classmethod
    def review_key(cls, ip_address: Optional[str] = None) -> "Principal":
        return cls(role=None, label="review-key", via="review_key", ip_address=ip_address,
                   permissions=REVIEW_KEY_PERMISSIONS)

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


class PermissionDenied(Exception):
    """Raised by authorize(); the API answers 403 (app.main)."""

    def __init__(self, permission: Permission, message: str = "You don't have permission to do this."):
        self.permission = permission
        self.message = message
        super().__init__(message)


def authorize(principal: Optional[Principal], permission: Permission) -> Principal:
    """Raise PermissionDenied unless the principal holds the permission (deny by default)."""
    if principal is None or not principal.can(permission):
        raise PermissionDenied(permission)
    if permission in _OWN_DATA and principal.account_pk is None:
        raise PermissionDenied(permission)        # own-data needs an account to be scoped to
    return principal
