"""Validate the skills touched by a pull request.

usage: python3 validate.py <base-ref>      (e.g. origin/main)

A skill counts as touched if ANY file under its folder changed (SKILL.md, scripts/,
references/, assets/), including deletions and renames. Exit 1 on any error.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skilllib as sl  # noqa: E402


def plugin_dir(skill_dir):
    return skill_dir.rsplit("/", 1)[0] if "/" in skill_dir else "."


def read_json(ref, path):
    text = sl.show(ref, path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: invalid JSON ({e})") from None


def check_manifests(mb, head_dirs, base_dirs, touched):
    """Claude Code reads the marketplace straight from the repo, so the manifests must match
    the skill folders, and a plugin's version must go up whenever one of its skills changes
    (Claude Code only updates a plugin when plugin.json's version changes)."""
    errors = []
    try:
        mkt = read_json("HEAD", ".claude-plugin/marketplace.json")
    except ValueError as e:
        return [str(e)]
    if not mkt:
        return [".claude-plugin/marketplace.json is missing"]
    listed = {}
    for entry in mkt.get("plugins", []):
        src = str(entry.get("source", "")).removeprefix("./").rstrip("/") or "."
        listed[src] = entry.get("name")
    needed = {plugin_dir(d) for d in head_dirs if not d.startswith(".github/")}
    for pd in sorted(needed - set(listed)):
        errors.append(f"{pd}: contains skills but is not listed in .claude-plugin/marketplace.json")
    for pd, name in sorted(listed.items()):
        mpath = f"{pd}/.claude-plugin/plugin.json"
        try:
            man = read_json("HEAD", mpath)
        except ValueError as e:
            errors.append(str(e)); continue
        if man is None:
            errors.append(f"{mpath} is missing (listed in marketplace.json as '{name}')"); continue
        if man.get("name") != name:
            errors.append(f"{mpath}: name '{man.get('name')}' differs from marketplace entry '{name}'")
        if not sl.semver(str(man.get("version", ""))):
            errors.append(f"{mpath}: version '{man.get('version')}' must be major.minor.patch")
        if pd not in needed:
            errors.append(f"{pd}: listed in marketplace.json but has no skills (remove the entry)")
    for pd in sorted({plugin_dir(d) for d in touched}):
        mpath = f"{pd}/.claude-plugin/plugin.json"
        try:
            new, old = read_json("HEAD", mpath), read_json(mb, mpath)
        except ValueError:
            continue
        if new and old:
            nv, ov = sl.semver(str(new.get("version", ""))), sl.semver(str(old.get("version", "")))
            if nv and ov and nv <= ov:
                errors.append(f"{mpath}: a skill in this plugin changed, bump the plugin version (still {new.get('version')})")
    return errors


def main(base):
    if not sl.ref_exists(base):
        print(f"::error::base ref '{base}' not found (did checkout use fetch-depth: 0?)")
        return 1
    if not sl.ref_exists("HEAD"):
        print("::error::HEAD is not a commit")
        return 1
    mb = sl.git("merge-base", base, "HEAD").stdout.strip()
    diff = sl.git("diff", "--name-status", "-z", "-M", mb, "HEAD").stdout.split("\0")

    changed = []
    i = 0
    while i < len(diff) and diff[i]:
        status = diff[i]
        if status[0] in "RC":
            changed += [diff[i + 1], diff[i + 2]]
            i += 3
        else:
            changed.append(diff[i + 1])
            i += 2

    head_dirs, base_dirs = sl.skill_dirs("HEAD"), sl.skill_dirs(mb)
    touched = set()
    for path in changed:
        owner = sl.owning_skill(path, head_dirs) or sl.owning_skill(path, base_dirs)
        if owner:
            touched.add(owner)

    errors, notices = [], []

    # names must be unique across the whole repo (tags and installs are keyed by name)
    seen = {}
    for d in sorted(head_dirs):
        leaf = d.rsplit("/", 1)[-1]
        if leaf in seen:
            errors.append(f"duplicate skill name '{leaf}': {seen[leaf]} and {d}")
        seen[leaf] = d

    for d in sorted(touched):
        path = f"{d}/SKILL.md"
        if d not in head_dirs:
            notices.append(f"{d}: skill deleted (allowed; mark it retired in the release notes)")
            continue
        try:
            fm = sl.parse_frontmatter(sl.show("HEAD", path))
        except ValueError as e:
            errors.append(f"{path}: {e}")
            continue
        errs, warns = sl.check_skill(d, fm)
        errors += [f"{path}: {e}" for e in errs]
        notices += [f"{path}: {w}" for w in warns]
        new = sl.semver(sl.version_of(fm))
        if d in base_dirs and new:
            try:
                old_v = sl.version_of(sl.parse_frontmatter(sl.show(mb, path)))
            except ValueError:
                old_v = None
            old = sl.semver(old_v)
            if old and new <= old:
                errors.append(f"{path}: skill changed but version {sl.version_of(fm)} is not higher than {old_v}")
        state = "changed" if d in base_dirs else "new"
        print(f"checked {d} ({state}) v{sl.version_of(fm)}")

    errors += check_manifests(mb, head_dirs, base_dirs, touched)
    for n in notices:
        print(f"::notice::{n}")
    for e in errors:
        print(f"::error::{e}")
    if not touched:
        print("no skills touched")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "origin/main"))
