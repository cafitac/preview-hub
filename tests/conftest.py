from pathlib import Path

import pytest

from preview_hub.contracts import Catalog, CatalogEntry, ServiceManifest
from preview_hub.lifecycle import Context
from preview_hub.registry import Registry
from preview_hub.runners.fake import FakeRunner


def manifest(name="backend", **extra):
    return ServiceManifest.parse(
        {
            "apiVersion": "preview-hub/v1",
            "service": name,
            "build": {"context": ".", "dockerfile": "Dockerfile"},
            "run": {"port": 8000},
            "health": {"http": "/healthz", "timeout": "1s"},
            **extra,
        }
    )


class FakeGit:
    def __init__(self, root: Path):
        self.root = root
        self.sha = "a" * 40
        self.fail = False
        self.manifests = {"org/backend": manifest()}
        self.resolutions = 0

    def resolve(self, repo, ref):
        self.resolutions += 1
        if self.fail:
            raise RuntimeError("synthetic resolve failure")
        return self.sha

    def checkout(self, repo, commit_sha):
        return self.root

    def read_manifest(self, repo, commit_sha):
        return self.manifests[repo]


@pytest.fixture
def ctx(tmp_path):
    return Context(
        Registry(tmp_path),
        Catalog(
            {"backend": CatalogEntry("org/backend", "main")},
            "http://{subdomain}.{env}.localhost:18080",
        ),
        FakeGit(tmp_path),
        FakeRunner(),
        free_space=lambda: 10 * 1024**3,
    )
