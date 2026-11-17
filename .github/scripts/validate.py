"""Validate changed skills against the base branch. Stdlib only."""
import re, subprocess, sys
from pathlib import Path

ALLOWED_TOP = {"name", "description", "license", "compatibility", "allowed-tools", "metadata"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout

def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return None
    top, meta, parent = {}, {}, None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        k, _, v = line.partition(":")
        if line[0] in " \t":
            if parent == "metadata":
                meta[k.strip()] = v.strip().strip('"')
        else:
            parent = k.strip()
            top[parent] = v.strip()
    return top, meta

base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
changed = sh("git", "diff", "--name-only", f"{base}...HEAD").split()
skills = sorted({str(Path(f).parent) for f in changed if Path(f).name == "SKILL.md"} |
                {str(p.parent) for f in changed for p in [Path(f)] for p in [*p.parents]
                 if (p / "SKILL.md").exists()})
errors = []
for d in skills:
    path = Path(d) / "SKILL.md"
    if not path.exists():
        continue
    fm = frontmatter(path.read_text())
    if not fm:
        errors.append(f"{path}: missing frontmatter"); continue
    top, meta = fm
    extra = set(top) - ALLOWED_TOP
    if extra:
        errors.append(f"{path}: non-standard top-level fields {sorted(extra)} (put them under metadata)")
    name = top.get("name", "")
    if name != Path(d).name:
        errors.append(f"{path}: name '{name}' must equal folder '{Path(d).name}'")
    if not NAME_RE.match(name) or len(name) > 40:
        errors.append(f"{path}: name must be lowercase-dash and <= 40 chars (Skill Registry limit)")
    if not top.get("description"):
        errors.append(f"{path}: description is required")
    ver = meta.get("version", "")
    if not SEMVER.match(ver):
        errors.append(f"{path}: metadata.version '{ver}' is not major.minor.patch"); continue
    old = sh("git", "show", f"{base}:{path}")
    if old:
        ofm = frontmatter(old)
        over = ofm[1].get("version", "0.0.0") if ofm else "0.0.0"
        if SEMVER.match(over) and tuple(map(int, ver.split("."))) <= tuple(map(int, over.split("."))):
            errors.append(f"{path}: changed but version {ver} not bumped (was {over})")
    print(f"checked {name} v{ver}")
for e in errors:
    print(f"::error::{e}")
sys.exit(1 if errors else 0)
