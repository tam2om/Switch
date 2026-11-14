"""Administrative command line.

  python -m app.cli init                      # apply reference data (roles, permissions, alert rules, models)
  python -m app.cli create-superadmin USER    # interactive, secure first-run Super Admin creation
  python -m app.cli verify-audit              # verify the audit hash chain
  python -m app.cli seed-simulator N          # demo/test only (requires ANM_SIMULATOR_ENABLED=true)
  python -m app.cli generate-key              # print a new encryption key for ANM_ENCRYPTION_KEYS
  python -m app.cli rotate-secrets            # re-encrypt stored secrets with the active key
"""

from __future__ import annotations

import getpass
import os
import sys

from sqlalchemy import func, select


def _db():  # type: ignore[no-untyped-def]
    from app.db.session import db_session

    return db_session()


def cmd_init() -> int:
    from app.services.bootstrap import sync_reference_data

    with _db() as db:
        sync_reference_data(db)
    print("Reference data synchronised.")
    return 0


def cmd_create_superadmin(username: str) -> int:
    from app.core.permissions import Role
    from app.core.security import password_policy_errors
    from app.models import User
    from app.services import audit
    from app.services.bootstrap import sync_reference_data
    from app.services.users import active_superadmin_count, create_user

    password = os.environ.pop("ANM_INITIAL_PASSWORD", None)
    if password is None:
        if not sys.stdin.isatty():
            print("Run interactively or provide ANM_INITIAL_PASSWORD for automation.", file=sys.stderr)
            return 2
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match.", file=sys.stderr)
            return 2
    errors = password_policy_errors(password, username)
    if errors:
        print("Password rejected: " + "; ".join(errors), file=sys.stderr)
        return 2
    with _db() as db:
        sync_reference_data(db)
        if active_superadmin_count(db) > 0 and os.environ.get("ANM_ALLOW_ADDITIONAL_SUPERADMIN") != "1":
            print("A Super Admin already exists. Create further users in the web UI "
                  "(or set ANM_ALLOW_ADDITIONAL_SUPERADMIN=1 for recovery).", file=sys.stderr)
            return 3
        if db.execute(select(User).where(func.lower(User.username) == username.lower())).first():
            print("Username already exists.", file=sys.stderr)
            return 3
        user = create_user(db, None, username=username, full_name="", email=None, role=Role.SUPER_ADMIN.value,
                           password=password, must_change_password=False)
        audit.record(db, action="setup.superadmin_created", category="security", actor_name="cli",
                     target_type="user", target_id=user.id)
    print(f"Super Admin '{username}' created.")
    return 0


def cmd_verify_audit() -> int:
    from app.services.audit import verify_chain

    with _db() as db:
        res = verify_chain(db)
    print(res)
    return 0 if res["valid"] else 1


def cmd_seed_simulator(n: int) -> int:
    from app.core.config import get_settings
    from app.services.simulator import seed

    if not get_settings().simulator_enabled:
        print("Simulator is disabled (set ANM_SIMULATOR_ENABLED=true in a demo/test environment).", file=sys.stderr)
        return 2
    with _db() as db:
        res = seed(db, n)
    print(res)
    return 0


def cmd_rotate() -> int:
    from app.core.crypto import get_keyring
    from app.models import IntegrationSetting, SwitchCredential, User

    ring = get_keyring()
    n = 0
    with _db() as db:
        for c in db.execute(select(SwitchCredential)).scalars():
            aad = f"switch-credential:{c.kind}"
            c.secret_enc = ring.encrypt_str(ring.decrypt_str(c.secret_enc, aad), aad)
            n += 1
        for u in db.execute(select(User).where(User.totp_secret_enc.is_not(None))).unique().scalars():
            aad = f"totp:{u.id}"
            u.totp_secret_enc = ring.encrypt_str(ring.decrypt_str(u.totp_secret_enc, aad), aad)
            n += 1
        for i in db.execute(select(IntegrationSetting).where(IntegrationSetting.secret_enc.is_not(None))).scalars():
            aad = f"integration:{i.kind}"
            i.secret_enc = ring.encrypt_str(ring.decrypt_str(i.secret_enc, aad), aad)
            n += 1
    print(f"Re-encrypted {n} secrets with key '{ring.active_id}'. Backups keep their original key; keep old keys "
          "in the key ring until those backups expire.")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "init":
        return cmd_init()
    if cmd == "create-superadmin" and len(argv) == 2:
        return cmd_create_superadmin(argv[1])
    if cmd == "verify-audit":
        return cmd_verify_audit()
    if cmd == "seed-simulator" and len(argv) == 2:
        return cmd_seed_simulator(int(argv[1]))
    if cmd == "generate-key":
        from app.core.crypto import generate_key

        print(generate_key())
        return 0
    if cmd == "rotate-secrets":
        return cmd_rotate()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
