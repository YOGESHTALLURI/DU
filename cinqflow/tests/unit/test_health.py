def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["wave"] == "0"

def test_auth_login_engineer(client):
    res = client.post("/api/v1/auth/login", json={"credential": "engineer:engineer123"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert "ENGINEER" in data["roles"]

def test_auth_login_readonly(client):
    res = client.post("/api/v1/auth/login", json={"credential": "readonly:readonly123"})
    assert res.status_code == 200
    data = res.json()
    assert "READ_ONLY" in data["roles"]

def test_auth_login_invalid(client):
    res = client.post("/api/v1/auth/login", json={"credential": "wrong:credentials"})
    assert res.status_code == 401

def test_auth_login_bad_format(client):
    res = client.post("/api/v1/auth/login", json={"credential": "nocodon"})
    assert res.status_code == 401