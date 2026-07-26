#!/bin/bash
# Build the submission zip from an exact git ref per the Slot checklist.
# usage: build_submission_zip.sh <git-ref> <out-name.zip>
set -euo pipefail
REF="${1:?git ref required}"; OUT="${2:?output zip name required}"
cd /Users/vedantmoghe/Downloads/optichallenge
TMP=$(mktemp -d)
git archive "$REF" submission/myalgorithm.py submission/README.md | tar -x -C "$TMP"
( cd "$TMP/submission" && zip -j -q "$TMP/$OUT" myalgorithm.py README.md )
# checklist 2: structure
python3 - "$TMP/$OUT" <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
names = z.namelist()
assert "myalgorithm.py" in names, f"myalgorithm.py not at root: {names}"
assert "utils.py" not in names, "utils.py must not be included"
assert all("/" not in n for n in names), f"nested paths found: {names}"
import os
sz = os.path.getsize(sys.argv[1])
assert sz <= 15 * 1024 * 1024, f"zip too large: {sz}"
print(f"structure OK: {names}, {sz} bytes")
PY
# checklist 3: byte-compare zipped file against the ref
python3 - "$TMP/$OUT" "$REF" <<'PY'
import sys, zipfile, subprocess
z = zipfile.ZipFile(sys.argv[1])
zipped = z.read("myalgorithm.py")
tagged = subprocess.check_output(["git", "show", f"{sys.argv[2]}:submission/myalgorithm.py"])
assert zipped == tagged, "zip content differs from git ref!"
print("byte-compare vs git ref: OK")
PY
cp "$TMP/$OUT" "submission/$OUT"
shasum -a 256 "submission/$OUT"
echo "BUILT: submission/$OUT from $REF"
