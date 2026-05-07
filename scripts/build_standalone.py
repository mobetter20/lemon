"""Build a single-file standalone version of the dashboard.

Inlines style.css, dashboard.js, and the latest data (real or mock) into one
HTML file you can save anywhere and double-click. Works on file:// — no server,
no fetch.

Usage:
    python scripts/build_standalone.py [output_path]

Default output: ~/Desktop/lemon.html
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(out_path: Path) -> int:
    html = (ROOT / "index.html").read_text()
    css = (ROOT / "style.css").read_text()
    js = (ROOT / "dashboard.js").read_text()

    # Pick the real data if it exists; fall back to mock
    real_path = ROOT / "data.json"
    mock_path = ROOT / "mock_data.json"
    if real_path.exists():
        data_path = real_path
        is_mock = False
    elif mock_path.exists():
        data_path = mock_path
        is_mock = True
    else:
        print("No data file found at repo root. Run scripts/v0_classify.py first.", file=sys.stderr)
        return 1

    with open(data_path) as f:
        data = json.load(f)

    # Inline CSS — replace the <link> tag
    html = html.replace(
        '<link rel="stylesheet" href="style.css">',
        f"<style>\n{css}\n</style>",
    )

    # Inline JS with embedded data (compact JSON to keep file size reasonable)
    embedded = f"const EMBEDDED_DATA = {json.dumps(data, separators=(',', ':'))};\n"
    html = html.replace(
        '<script src="dashboard.js" defer></script>',
        f"<script>\n{embedded}{js}\n</script>",
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)

    size_kb = out_path.stat().st_size / 1024
    label = "MOCK" if is_mock else "REAL"
    print(f"Wrote {out_path} ({size_kb:.1f} KB · {label} data from {data_path.name})")
    if not is_mock:
        for fam in ("claude", "openai"):
            s = data["summary"][fam]
            print(
                f"  {fam} {s['this_week_label']}: "
                f"{s['this_week']['rate']:.1%} ({s['this_week']['complaints']}/{s['this_week']['all_mentions']})"
            )
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Desktop" / "lemon.html"
    sys.exit(main(out))
