"""
Set an account's role from the server (docs/RBAC.md).

The only way to create the FIRST administrator: no API route can, and nobody can
change their own role through the API. Needs direct database access (DATABASE_URL),
so it can only be run by whoever operates the server. The change is audited
(actor "cli:set_role"), the account's sessions are revoked, and the last active
administrator can't be demoted here either.

Usage:
  python scripts/set_role.py farmer@example.com ADMIN
  docker compose exec backend python ../scripts/set_role.py farmer@example.com REVIEWER --approve

A REVIEWER can work review cases only once approved (docs/HUMAN_REVIEW.md); an administrator
does that on /admin, or --approve does it here (audited as "cli:set_role").
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.permissions import Principal, Role  # noqa: E402
from app.database.connection import close_db, init_db, is_db_available, use_selector_event_loop_on_windows  # noqa: E402
from app.database.repositories import admin_repository  # noqa: E402
from app.database.repositories import auth_repository  # noqa: E402

use_selector_event_loop_on_windows()


async def main(email: str, role: Role, approve: bool = False) -> int:
    await init_db()
    try:
        if not is_db_available():
            print("Database not connected: set DATABASE_URL.")
            return 2
        account = await auth_repository.get_farmer_by_email(email)
        if account is None:
            print(f"No account with e-mail {email}. Register it first.")
            return 1
        actor = Principal(role=None, label="cli:set_role", via="cli")
        try:
            row = await admin_repository.set_role(actor, account.farmer_id, role, None)
        except admin_repository.AdminRejected as exc:
            print(f"Refused: {exc.message}")
            return 1
        print(f"{row.email}: role is now {row.role} (sessions revoked; sign in again).")
        if approve:
            if role != Role.REVIEWER:
                print("--approve applies to REVIEWER accounts only.")
                return 1
            try:
                await admin_repository.set_reviewer_approval(actor, account.farmer_id, True)
            except admin_repository.AdminRejected as exc:
                print(f"Approval refused: {exc.message}")
                return 1
            print(f"{row.email}: approved for review work.")
        return 0
    finally:
        await close_db()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("email")
    ap.add_argument("role", choices=[r.value for r in Role])
    ap.add_argument("--approve", action="store_true", help="also approve a REVIEWER for review work")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.email, Role(args.role), args.approve)))
