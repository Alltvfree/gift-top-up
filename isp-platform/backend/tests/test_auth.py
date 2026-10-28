from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import PASSWORD, login


def test_requires_login():
    assert TestClient(app).get("/api/summary").status_code == 401


def test_login_and_me():
    c = login("nina")
    me = c.get("/api/auth/me").json()
    assert me["role"] == "noc" and "network" in me["permissions"] and "approve" not in me["permissions"]


def test_bad_password_generic_error_and_lockout():
    c = TestClient(app)
    for _ in range(5):
        r = c.post("/api/auth/login", json={"username": "sam", "password": "wrong"})
        assert r.status_code == 401 and r.json()["detail"] == "Invalid username or password"
    # Locked now, even with the right password
    assert c.post("/api/auth/login", json={"username": "sam", "password": PASSWORD}).status_code == 401
    # Unknown users get the same answer
    assert c.post("/api/auth/login", json={"username": "nobody", "password": "x"}).json()["detail"] == "Invalid username or password"


def test_ip_throttle():
    c = TestClient(app)
    for i in range(20):
        c.post("/api/auth/login", json={"username": f"ghost{i}", "password": "x"})
    assert c.post("/api/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 429


def test_csrf_header_required_for_writes():
    c = login("alice")
    del c.headers["X-Requested-With"]
    assert c.post("/api/islands", json={"code": "X1", "name": "X"}).status_code == 403


def test_rbac():
    assert login("sam").post("/api/islands", json={"code": "S1", "name": "S"}).status_code == 403
    assert login("bill").post("/api/islands", json={"code": "S1", "name": "S"}).status_code == 403
    assert login("nina").get("/api/users").status_code == 403
    assert login("alice").get("/api/users").status_code == 200


def test_logout_kills_session():
    c = login("nina")
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_weak_password_rejected(admin):
    r = admin.post("/api/users", json={"username": "weak", "role": "support", "password": "short"})
    assert r.status_code == 400
