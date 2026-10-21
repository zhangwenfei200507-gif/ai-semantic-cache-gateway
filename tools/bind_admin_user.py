"""Bind the configured immutable user id to the database admin flag.

This is an explicit one-time administrative operation. It never accepts an
email address, never creates users, and refuses to run when ADMIN_USER_ID is
not configured or the requested id does not match it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.database import get_connection, init_db
from app.config.settings import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind the configured user id as the platform administrator")
    parser.add_argument("--user-id", type=int, required=True)
    args = parser.parse_args()
    configured = settings.admin_user_id
    if configured is None or int(configured) != args.user_id:
        raise SystemExit("ADMIN_USER_ID must be configured and match --user-id")
    init_db()
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (args.user_id,)).fetchone()
        if row is None:
            raise SystemExit("Configured admin user does not exist")
        conn.execute("UPDATE users SET is_admin = TRUE, updated_at = updated_at WHERE id = ?", (args.user_id,))
        conn.commit()
    print(f"Administrator binding applied for user id {args.user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
