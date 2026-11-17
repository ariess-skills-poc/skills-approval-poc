"""Validate the skills touched by a pull request.

usage: python3 validate.py <base-ref>      (e.g. origin/main)

A skill counts as touched if ANY file under its folder changed (SKILL.md, scripts/,
references/, assets/), including deletions and renames. Exit 1 on any error.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skilllib as sl  # noqa: E402


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

    for n in notices:
        print(f"::notice::{n}")
    for e in errors:
        print(f"::error::{e}")
    if not touched:
        print("no skills touched")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "origin/main"))
