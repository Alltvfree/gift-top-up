"""Admin CLI.  docker compose exec api python -m app.cli create-admin <username>"""
import getpass
import sys

from . import db
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
    print(f"admin '{username}' ready")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "create-admin":
        create_admin(sys.argv[2].lower())
    else:
        sys.exit(__doc__)
