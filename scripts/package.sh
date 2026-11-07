#!/usr/bin/env bash
# Builds the zip people install Harbor from (Claude Code: /plugin install from a file; claude.ai: Customize →
# Plugins → Upload), and checks it the way claude.ai's upload does:
#
#   scripts/package.sh [ref] [out.zip]      # defaults: HEAD, dist/harbor-plugin.zip
#
# The zip holds the plugin at its root — .claude-plugin/, skills/, agents/, hooks/, bin/ and docs/design.md (the
# skills and agents read it) — plus README, README.es, CHANGELOG and LICENSE. It leaves out what only this repository
# needs: its CI (.github/), its tests and scripts, and docs/releasing.md. The Release workflow attaches it to every
# GitHub Release as harbor-plugin.zip.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

ref=${1:-HEAD}
out=${2:-dist/harbor-plugin.zip}
fail() { echo "package: $*" >&2; exit 1; }

git rev-parse -q --verify "$ref^{commit}" >/dev/null || fail "no such commit: $ref"
mkdir -p "$(dirname "$out")"
out=$(cd "$(dirname "$out")" && pwd)/$(basename "$out")
rm -f "$out"

git archive --format=zip -o "$out" "$ref" -- . \
  ':(exclude).github' ':(exclude)tests' ':(exclude)scripts' ':(exclude)docs/releasing.md' ':(exclude).gitignore'

python3 - "$out" <<'PY'
import json, re, sys, zipfile
path = sys.argv[1]
z = zipfile.ZipFile(path)
names = z.namelist()
def fail(msg):
    sys.exit(f"package: {msg}")
if ".claude-plugin/plugin.json" not in names:
    fail("no .claude-plugin/plugin.json at the zip's root")
version = json.loads(z.read(".claude-plugin/plugin.json"))["version"]
unsafe = [n for n in names if not re.fullmatch(r"[A-Za-z0-9._/@+-]+", n)]
if unsafe:
    fail(f"paths claude.ai rejects: {unsafe[:5]}")
for n in names:
    if re.fullmatch(r"(skills/[^/]+/SKILL|agents/[^/]+)\.md", n):
        m = re.search(r"(?m)^description:(.*)$", z.read(n).decode())
        if m and re.search(r"<[^>]+>", m.group(1)):
            fail(f"{n}: a description with tag-like text")
for need in ("skills/adopt/SKILL.md", "skills/convoy/SKILL.md", "hooks/hooks.json", "bin/harbor.py", "docs/design.md"):
    if need not in names:
        fail(f"missing {need}")
skills = sorted({n.split("/")[1] for n in names if n.startswith("skills/") and n.count("/") >= 2})
print(f"package: {path} — Harbor {version}, {len(names)} entries, {len(skills)} skills")
PY
