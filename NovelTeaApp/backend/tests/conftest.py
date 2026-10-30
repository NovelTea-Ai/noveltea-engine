"""Test setup: every test runs against a throwaway home folder and corpus, never your real ones."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent.parent

_home = Path(tempfile.mkdtemp(prefix="noveltea_test_home_"))
_corpus = _home / "corpus"
for sub in ("projects", "generated", "novels", "raw"):
    (_corpus / sub).mkdir(parents=True)
(_home / ".noveltea-engine").mkdir()
(_home / ".noveltea-engine" / "config.json").write_text(json.dumps({"corpus_path": str(_corpus)}), encoding="utf-8")
os.environ["HOME"] = os.environ["USERPROFILE"] = str(_home)     # read when config.py is imported
sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope="session")
def corpus() -> Path:
    return _corpus


@pytest.fixture(scope="session")
def demo_project(corpus) -> str:
    """The shipped demo project, copied into the test corpus."""
    pid = "the_lantern_court"
    shutil.copytree(REPO / "demo" / pid, corpus / "projects" / pid, ignore=shutil.ignore_patterns("generated", "README.md"))
    shutil.copytree(REPO / "demo" / pid / "generated", corpus / "generated" / pid)
    (corpus / "projects" / "registry.json").write_text(json.dumps([{"id": pid, "title": "The Lantern Court"}]), encoding="utf-8")
    return pid


@pytest.fixture(scope="session")
def client(demo_project):
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_home, ignore_errors=True)
