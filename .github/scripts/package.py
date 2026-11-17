"""Build the published skill catalog from a commit on main.

usage: python3 .github/scripts/package.py <out-dir> [--ref HEAD]

Output (upload <out-dir> to gs://<bucket>/current/):
  .claude-plugin/marketplace.json   Claude Code marketplace: one plugin per <dominio>/<ambito>/<foglia>
  <dominio>/<ambito>/<foglia>/.claude-plugin/plugin.json
  <dominio>/<ambito>/<foglia>/<skill>/...   skill folders, copied as they are on main
  index.json                        catalog for people, Data Portal and the find-skill agent
  release.json                      which commit this catalog was built from

Rules:
  - Only what is on <ref> (main) is published. A tag pushed on some other commit is ignored.
  - Each skill's version must have its release tag, and the tag must point to a commit on <ref>.
    Otherwise the build fails (the release workflow tags first, then this runs).
  - lifecycle: retired skills are left out; deprecated skills stay, flagged in index.json.
  - Plugin version = 0.<commits touching the plugin folder>.0, so it grows whenever any skill in it changes.
"""
import json, subprocess, sys
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skilllib as sl  # noqa: E402

MARKETPLACE = "unieuro-skills"


def codeowners(ref):
    text = sl.show(ref, "CODEOWNERS") or sl.show(ref, ".github/CODEOWNERS") or ""
    rules = []
    for line in text.splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) >= 2:
            rules.append((parts[0].strip("/"), parts[1:]))
    return rules


def owner_of(rules, path):
    owners = []
    for pat, who in rules:  # GitHub: last matching line wins
        if ("*" in pat and fnmatch(path, pat)) or path == pat or path.startswith(pat + "/"):
            owners = who
    return " ".join(owners)


def plugin_dir_of(skill_dir):
    parent = skill_dir.rsplit("/", 1)[0] if "/" in skill_dir else ""
    return parent or "."


def plugin_name_of(plugin_dir):
    parts = [p for p in plugin_dir.split("/") if p and p != "."]
    if not parts:
        return "root"
    return f"{parts[0]}-{parts[-1]}" if len(parts) > 1 else parts[0]


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    out = Path(args[0])
    ref = args[args.index("--ref") + 1] if "--ref" in args else "HEAD"
    if out.exists() and any(out.iterdir()):
        sys.exit(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    commit = sl.git("rev-parse", ref).stdout.strip()
    rules = codeowners(ref)

    skills, errors = [], []
    for d in sorted(sl.skill_dirs(ref)):
        if d.startswith(".github/"):
            continue
        fm = sl.parse_frontmatter(sl.show(ref, f"{d}/SKILL.md"))
        errs, _ = sl.check_skill(d, fm)
        if errs:
            errors += [f"{d}: {e}" for e in errs]
            continue
        meta = fm.get("metadata") or {}
        lifecycle = meta.get("lifecycle", "stable")
        if lifecycle == "retired":
            continue
        ver = sl.version_of(fm)
        tag = sl.tag_name(fm["name"], ver)
        if not sl.ref_exists(tag):
            errors.append(f"{d}: release tag {tag} missing")
            continue
        if sl.git("merge-base", "--is-ancestor", tag, ref, check=False).returncode != 0:
            errors.append(f"{d}: tag {tag} is not on {ref}")
            continue
        pdir = plugin_dir_of(d)
        skills.append({
            "name": fm["name"], "description": " ".join(str(fm["description"]).split()),
            "version": ver, "lifecycle": lifecycle,
            "replaced_by": meta.get("replaced_by"), "sunset": meta.get("sunset"),
            "author": meta.get("author"), "owner": owner_of(rules, d),
            "path": d, "plugin": plugin_name_of(pdir), "plugin_dir": pdir, "tag": tag,
            "install": f"uni-skills install {fm['name']}",
        })
    if errors:
        for e in errors:
            print(f"::error::{e}")
        sys.exit(1)

    # copy skill folders exactly as they are on ref
    for s in skills:
        files = sl.git("ls-tree", "-r", "-z", "--name-only", ref, "--", s["path"]).stdout.split("\0")
        for f in filter(None, files):
            blob = subprocess.run(["git", "show", f"{ref}:{f}"], capture_output=True, check=True).stdout
            dst = out / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(blob)

    plugins = {}
    for s in skills:
        plugins.setdefault(s["plugin"], {"dir": s["plugin_dir"], "skills": []})["skills"].append(s)
    entries = []
    for name, p in sorted(plugins.items()):
        n = int(sl.git("rev-list", "--count", ref, "--", p["dir"]).stdout.strip() or 0)
        version = f"0.{n}.0"
        desc = "; ".join(f"{s['name']} v{s['version']}" for s in p["skills"])
        manifest = {"name": name, "version": version, "description": desc, "skills": "./"}
        pd = out / p["dir"] / ".claude-plugin"
        pd.mkdir(parents=True, exist_ok=True)
        (pd / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n")
        entries.append({"name": name, "source": f"./{p['dir']}", "version": version, "description": desc})
        for s in p["skills"]:
            s["plugin_version"] = version

    (out / ".claude-plugin").mkdir(exist_ok=True)
    (out / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": MARKETPLACE, "owner": {"name": "Unieuro skills catalog"},
         "description": "Published Unieuro agent skills", "plugins": entries}, indent=2) + "\n")
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out / "index.json").write_text(json.dumps(
        {"marketplace": MARKETPLACE, "commit": commit, "built_at": built, "skills": skills}, indent=2) + "\n")
    (out / "release.json").write_text(json.dumps({"commit": commit, "built_at": built}) + "\n")
    print(f"built {len(skills)} skills in {len(entries)} plugins from {commit[:7]} -> {out}")


if __name__ == "__main__":
    main()
