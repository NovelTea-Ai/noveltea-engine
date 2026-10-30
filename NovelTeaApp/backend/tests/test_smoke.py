"""Every route that needs no arguments must answer without a server error."""

SKIP = ("restart", "shutdown")


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_parameterless_get_routes_do_not_crash(client):
    paths = client.get("/openapi.json").json()["paths"]
    failures = []
    for path, ops in sorted(paths.items()):
        if "{" in path or any(s in path for s in SKIP) or "get" not in ops:
            continue
        r = client.get(path)
        if r.status_code >= 500:
            failures.append((path, r.status_code, r.text[:120]))
    assert not failures, failures


def test_no_removed_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if p.startswith("/api/nemotron")], "the shell-command agent API must not be exposed"
