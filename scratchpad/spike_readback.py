"""Compose spike readback: run the manifest's cells through
convert.targeted over a pulled .pdf.mark and print the three-way decision
per cell (Analysis 0009 F4: blank / ANSWERED / AMBIGUOUS-escalate).

Run:  uv run python scratchpad/spike_readback.py <pulled .pdf.mark>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from inkbridge.convert.targeted import region_ink_coverage

AMBIGUOUS_FLOOR = 0.001   # ~stray-dot territory starts here (0009 F4)
ANSWERED_LINE = 0.004     # above the lightest real answer band

MANIFEST_PATH = Path(__file__).parent / "spike_001.manifest.json"


def main(mark_path: str) -> int:
    manifest = json.loads(MANIFEST_PATH.read_text())
    print(f"mark: {mark_path}\ndoc:  {manifest['doc_id']}\n")
    print(f"{'cell':16} {'type':16} {'coverage %':>10}  decision")
    for cell in manifest["cells"]:
        cov = region_ink_coverage(
            Path(mark_path), cell["page"], tuple(cell["bbox_norm"])
        )
        if cov <= 0.0:
            decision = "blank"
        elif cov < AMBIGUOUS_FLOOR:
            decision = "blank (sub-stray)"
        elif cov < ANSWERED_LINE:
            decision = "AMBIGUOUS -> escalate"
        else:
            decision = "ANSWERED"
        print(f"{cell['id']:16} {cell['type']:16} {cov * 100:>10.4f}  {decision}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
