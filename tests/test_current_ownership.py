"""REVIEW28-26: only the current sidecar can establish live output ownership."""
import json

import pytest

from articulous.ownership import ownership_path
from articulous.pipeline import run_build
from articulous.publication import build_site
from test_prepared_build import snapshot


@pytest.mark.parametrize("publisher", [run_build, build_site])
@pytest.mark.parametrize("defect", ["missing", "version1", "generation", "translations", "routes", "incomplete"])
def test_review28_26_requires_current_ownership(site_root, seo_config, publisher, defect):
    cli, config = seo_config
    publisher(cli, config, site_root)
    output = site_root / "output"
    sidecar = ownership_path(output)
    cache = site_root / ".build-cache.json"
    data = json.loads(sidecar.read_text())
    if defect == "missing":
        sidecar.unlink()
    else:
        _damage_ownership(data, defect)
        sidecar.write_text(json.dumps(data))
    (site_root / "content/en/first-post.xml").unlink()
    before = snapshot(output), cache.read_bytes()
    state = sidecar.read_bytes() if sidecar.exists() else None
    with pytest.raises(ValueError, match="restore|empty output"):
        publisher(cli, config, site_root)
    assert (snapshot(output), cache.read_bytes()) == before
    assert (sidecar.read_bytes() if sidecar.exists() else None) == state


def _damage_ownership(data, defect):
    if defect == "version1":
        data.update(version=1, outputs={key: path for path, key in data["paths"].items()})
    elif defect == "incomplete":
        del data["routes"]["article:en:first-post"]
    else:
        del data[defect]
