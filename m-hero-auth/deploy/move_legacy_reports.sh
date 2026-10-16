#!/bin/bash
# Move old-engine / non-summary report workbooks out of the served output/ dir into output/_legacy/ (MOVE ONLY, never delete).
# usage: move_legacy_reports.sh [--apply]      default = dry run (prints what would move)
# A workbook stays in output/ only if: its name has no legacy marker (_公式版, 新模板, _legacy) AND it has only the 5 summary sheets.
set -euo pipefail
OUT=${OUT:-$HOME/m-hero-prod/mhero_district_form/output}
python3 - "$OUT" "${1:-}" <<'PY'
import sys, re, zipfile, shutil, glob, os, time
out, apply = sys.argv[1], sys.argv[2] == "--apply"
S = {"总表", "区域指标排序", "直营店指标", "直营店指标排序", "常备件备库率"}
dest = os.path.join(out, "_legacy"); moved = 0
for p in sorted(glob.glob(os.path.join(out, "区域各指标情况一览*.xlsx"))):
    n = os.path.basename(p)
    try: names = re.findall(r'<sheet\b[^>]*?\bname="([^"]+)"', zipfile.ZipFile(p).read("xl/workbook.xml").decode())
    except Exception: names = []
    legacy = any(k in n for k in ("_公式版", "新模板", "_legacy")) or not names or not set(names) <= S
    print(("MOVE " if legacy else "KEEP ") + n + ("" if not legacy else f"  ({len(names)} sheets)"))
    if legacy and apply:
        os.makedirs(dest, exist_ok=True); t = os.path.join(dest, n)
        if os.path.exists(t): t = os.path.join(dest, f"{int(time.time())}_{n}")
        shutil.move(p, t); moved += 1
print(f"{'moved' if apply else 'would move'} {moved if apply else sum(1 for _ in [])}" if apply else "dry run — nothing moved; add --apply")
PY
