"""The standalone browser demo embeds policy.json; make sure it cannot drift silently."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_standalone_demo_embeds_current_policy():
    html = (ROOT / "docs" / "standalone-demo.html").read_text()
    policy = json.loads((ROOT / "app" / "policy.json").read_text())
    assert html.startswith("<!doctype html>")
    assert f'"version": "{policy["version"]}"' in html
    for band in policy["bands"]:
        assert f'"name": "{band["name"]}"' in html
    # every sample merchant is present
    assert all(f'"M-{n}"' in html for n in range(1001, 1061))
