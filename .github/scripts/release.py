"""Tag skills whose version changed in a push to main.

usage: python3 release.py <before-sha> <after-sha> [--push]

- Only skills whose metadata.version differs between <before> and <after> are tagged.
- First push (before = 000…0 or unknown): every skill without a tag is tagged.
- Never re-tags. If a tag already exists on a different commit, fails loudly.
- Tag: <name>--v<version>, annotated, message includes the PR number when found.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skilllib as sl  # noqa: E402


def pr_number(sha):
    msg = sl.git("log", "-1", "--format=%s%n%b", sha).stdout
    m = re.search(r"Merge pull request #(\d+)", msg) or re.search(r"\(#(\d+)\)", msg)
    return m.group(1) if m else None


def main(before, after, push):
    if not sl.ref_exists(after):
        print(f"::error::after sha {after} not found")
        return 1
    first = before in ("", sl.ZERO_SHA) or not sl.ref_exists(before)
    before_dirs = set() if first else sl.skill_dirs(before)
    pr = pr_number(after)
    errors, created = [], []

    for d in sorted(sl.skill_dirs(after)):
        path = f"{d}/SKILL.md"
        try:
            fm = sl.parse_frontmatter(sl.show(after, path))
        except ValueError as e:
            errors.append(f"{path}: {e}")
            continue
        name, ver = fm.get("name"), sl.version_of(fm)
        if not (isinstance(name, str) and sl.NAME_RE.match(name) and sl.semver(ver)):
            errors.append(f"{path}: invalid name/version ({name!r}, {ver!r}); not tagging")
            continue
        if d in before_dirs:
            try:
                old = sl.version_of(sl.parse_frontmatter(sl.show(before, path)))
            except ValueError:
                old = None
            if old == ver:
                continue
        tag = sl.tag_name(name, ver)
        existing = sl.git("rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}", check=False)
        if existing.returncode == 0:
            if existing.stdout.strip() == sl.git("rev-parse", after).stdout.strip():
                continue  # re-run of the same push
            if not first:
                errors.append(f"{tag} already exists on another commit: version reused, not re-tagging")
            continue
        msg = f"release {name} v{ver}" + (f" (PR #{pr})" if pr else "")
        sl.git("tag", "-a", tag, "-m", msg, after)
        created.append(tag)
        print(f"tagged {tag}")

    if push and created:
        sl.git("push", "origin", *[f"refs/tags/{t}" for t in created])
    for e in errors:
        print(f"::error::{e}")
    if not created:
        print("no new versions to tag")
    return 1 if errors else 0


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if x != "--push"]
    sys.exit(main(a[0] if a else "", a[1] if len(a) > 1 else "HEAD", "--push" in sys.argv))
