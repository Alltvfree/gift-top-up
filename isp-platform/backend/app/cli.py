"""Admin CLI (needs shell access to the server):
  docker compose exec api python -m app.cli create-admin <username>
  docker compose exec api python -m app.cli reset-mfa <username>   # lost phone and recovery codes
"""
import getpass
import sys

from . import audit, db
from .migrate import migrate
from .security import hash_password, password_problem


def create_admin(username: str):
    migrate()
    password = getpass.getpass("Password (12+ chars, upper/lower/digit): ")
    if problem := password_problem(password):
        sys.exit(problem)
    if password != getpass.getpass("Repeat: "):
        sys.exit("Passwords differ")
    db.run("""INSERT INTO users(username,full_name,role,password_hash) VALUES (%s,%s,'admin',%s)
              ON CONFLICT (username) DO UPDATE SET password_hash=EXCLUDED.password_hash, role='admin', active=true,
              failed_logins=0, locked_until=NULL""", (username, username, hash_password(password)))
    print(f"admin '{username}' ready; set up two-factor at first sign-in")


def reset_mfa(username: str):
    migrate()
    with db.connect() as conn:
        row = conn.execute("""UPDATE users SET totp_enabled=false, totp_secret_enc=NULL, totp_last_step=0
                              WHERE username=%s RETURNING id""", (username,)).fetchone()
        if not row:
            sys.exit(f"no user '{username}'")
        conn.execute("DELETE FROM user_recovery_codes WHERE user_id=%s", (row["id"],))
        conn.execute("DELETE FROM sessions WHERE user_id=%s", (row["id"],))
        audit.record("cli", "user.mfa_reset", "user", row["id"], {"username": username}, conn=conn)
    print(f"two-factor reset for '{username}'; they enrol again at next sign-in")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "create-admin":
        create_admin(sys.argv[2].lower())
    elif len(sys.argv) == 3 and sys.argv[1] == "reset-mfa":
        reset_mfa(sys.argv[2].lower())
    else:
        sys.exit(__doc__)
