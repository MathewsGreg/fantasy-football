"""Build the self-contained draft-board HTML from a FantasyPros export.

Usage:
    python build_board.py [path/to/cheatsheet.csv]

If no CSV path is given, uses data/cheatsheet.csv if present, otherwise
falls back to data/sample_cheatsheet.csv (clearly-labeled placeholder data
for testing the pipeline before you have a real export).

Writes site/draft_board.html — open it directly in a browser, no server
needed.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ingest import load_cheatsheet
from vbd import annotate

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    config = json.loads((ROOT / "league_config.json").read_text())

    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])
        is_sample = False
    else:
        real = ROOT / "data" / "cheatsheet.csv"
        sample = ROOT / "data" / "sample_cheatsheet.csv"
        if real.exists():
            csv_path = real
            is_sample = False
        else:
            csv_path = sample
            is_sample = True
            print(f"No {real} found — building with placeholder sample data instead.")

    players = load_cheatsheet(str(csv_path))
    annotated = annotate(players, config)

    template = (Path(__file__).parent / "board_template.html").read_text()
    html = (
        template
        .replace("__CONFIG_JSON__", json.dumps(config))
        .replace("__DATA_JSON__", json.dumps(annotated))
        .replace("__IS_SAMPLE_JSON__", json.dumps(is_sample))
        .replace("__GENERATED_AT_JSON__", json.dumps(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")))
    )

    out_dir = ROOT / "site"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "draft_board.html"
    out_path.write_text(html)
    print(f"Wrote {out_path} ({len(annotated)} players, source={csv_path.name}, sample={is_sample})")


if __name__ == "__main__":
    main()
