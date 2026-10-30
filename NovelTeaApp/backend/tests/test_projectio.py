"""Project import / export: the bundle format, round trips, manuscripts, hostile files and rollback."""
import hashlib
import io
import json
import zipfile

import pytest


def _zip(entries, symlink=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = 0o120777 << 16
            z.writestr(info, "/etc/passwd")
    return buf.getvalue()


@pytest.fixture
def preview(client):
    def go(data, name):
        return client.post("/api/project-io/import/preview", files={"file": (name, data)})
    return go


@pytest.fixture(scope="module")
def bundle(client, demo_project):
    r = client.get(f"/api/project-io/export/{demo_project}?format=bundle")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    return r.content


def test_bundle_contents(bundle):
    z = zipfile.ZipFile(io.BytesIO(bundle))
    manifest = json.loads(z.read("manifest.json"))
    assert manifest["format"] == "noveltea-project" and manifest["formatVersion"] == 1
    assert "project.json" in z.namelist()
    assert all(hashlib.sha256(z.read(e["path"])).hexdigest() == e["sha256"] for e in manifest["files"])
    assert not [n for n in z.namelist() if n.endswith((".wav", ".mp3")) or ".bak" in n or "BROKEN" in n]


def test_manuscript_exports(client, demo_project):
    md = client.get(f"/api/project-io/export/{demo_project}?format=markdown")
    assert md.status_code == 200 and md.text.startswith("# ")
    assert client.get(f"/api/project-io/export/{demo_project}?format=txt").status_code == 200
    assert client.get(f"/api/project-io/export/{demo_project}?format=pdf").status_code == 400
    assert client.get("/api/project-io/export/does_not_exist_1?format=bundle").status_code == 404
    assert client.get("/api/project-io/export/..%2f..%2fetc?format=bundle").status_code in (400, 404)


def test_round_trip(client, preview, bundle, demo_project):
    pv = preview(bundle, "mine.noveltea.zip")
    assert pv.status_code == 200 and pv.json()["kind"] == "bundle"
    done = client.post("/api/project-io/import/commit", json={"token": pv.json()["token"]})
    assert done.status_code == 200
    new_id = done.json()["id"]
    assert new_id != demo_project
    again = zipfile.ZipFile(io.BytesIO(client.get(f"/api/project-io/export/{new_id}?format=bundle").content))
    first = zipfile.ZipFile(io.BytesIO(bundle))
    assert all(first.read(n) == again.read(n) for n in first.namelist() if n.startswith("generated/"))
    assert client.post("/api/project-io/import/commit", json={"token": pv.json()["token"]}).status_code == 404   # a token works once


def test_manuscript_import(client, preview):
    text = ("Chapter 1: The Start\n" + "word " * 150 + "\n\nChapter 2: Next\n" + "more " * 150 + "\n").encode()
    pv = preview(text, "My Novel.txt").json()
    assert pv["kind"] == "manuscript" and pv["chapters"] == 2
    done = client.post("/api/project-io/import/commit", json={"token": pv["token"], "title": "Renamed Novel"}).json()
    assert done["title"] == "Renamed Novel" and done["chapters"] == 2
    assert preview(b"hi", "e.txt").status_code == 400                      # nearly empty


GOOD = {"project.json": json.dumps({"title": "T"})}


@pytest.mark.parametrize("name,entries,symlink", [
    ("path traversal", {**GOOD, "../evil.json": "{}"}, None),
    ("absolute path", {**GOOD, "/etc/x.json": "{}"}, None),
    ("drive path", {**GOOD, "C:/x.json": "{}"}, None),
    ("symlink", GOOD, "link.json"),
    ("no project.json", {"readme.txt": "x"}, None),
    ("bad project.json", {"project.json": "{not json"}, None),
    ("no title", {"project.json": json.dumps({"x": 1})}, None),
    ("newer format", {**GOOD, "manifest.json": json.dumps({"format": "noveltea-project", "formatVersion": 99})}, None),
    ("other format", {**GOOD, "manifest.json": json.dumps({"format": "something-else"})}, None),
    ("checksum mismatch", {**GOOD, "manifest.json": json.dumps(
        {"format": "noveltea-project", "formatVersion": 1, "files": [{"path": "project.json", "sha256": "0" * 64}]})}, None),
])
def test_hostile_bundles_are_refused(preview, name, entries, symlink):
    assert preview(_zip(entries, symlink), "a.zip").status_code == 400, name


def test_other_hostile_inputs(client, preview):
    assert preview(b"this is not a zip", "a.zip").status_code == 400
    assert preview(b"x", "a.exe").status_code == 400
    for token in ("../../x", "short", "G" * 32, ""):
        assert client.post("/api/project-io/import/commit", json={"token": token}).status_code in (400, 404, 422)


def test_unknown_files_are_skipped(client, preview, corpus):
    pv = preview(_zip({**GOOD, "random.exe": "x", "generated/evil.sh": "x"}), "a.zip").json()
    assert pv["skipped_count"] == 2
    new_id = client.post("/api/project-io/import/commit", json={"token": pv["token"]}).json()["id"]
    assert not list((corpus / "projects" / new_id).glob("random.exe"))
    assert not (corpus / "generated" / new_id).exists()


def test_failed_import_leaves_nothing_behind(client, preview, corpus, monkeypatch):
    from routers.workspace import projects
    pv = preview(_zip({**GOOD, "generated/ch001_generated.txt": "x " * 50}), "a.zip").json()

    def names():
        return {p.name for p in (corpus / "projects").iterdir()} | {p.name for p in (corpus / "generated").iterdir()}

    before = names()
    monkeypatch.setattr(projects, "_save", lambda *_: (_ for _ in ()).throw(RuntimeError("disk full")))
    r = client.post("/api/project-io/import/commit", json={"token": pv["token"]})
    assert r.status_code == 500 and "undone" in r.text
    assert names() == before
