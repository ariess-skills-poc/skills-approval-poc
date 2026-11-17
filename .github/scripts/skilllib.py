"""Shared helpers for skill CI: git access and SKILL.md frontmatter parsing.

Used by validate.py (pull requests) and release.py (push to main).
Requires PyYAML (pinned in the workflows).
"""
import re
import subprocess

import yaml

# Top-level fields allowed by the Agent Skills spec. Everything else goes under `metadata`.
ALLOWED_TOP = {"name", "description", "license", "compatibility", "allowed-tools", "metadata"}
LIFECYCLES = {"experimental", "stable", "deprecated", "retired"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
MAX_NAME = 40  # Skill Registry limit is 63 and import appends a 16-char suffix
ZERO_SHA = "0" * 40


class GitError(RuntimeError):
    pass


def git(*args, cwd=None, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def ref_exists(ref, cwd=None):
    return git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=cwd, check=False).returncode == 0


def show(ref, path, cwd=None):
    """File content at ref, or None if the file does not exist there."""
    r = git("show", f"{ref}:{path}", cwd=cwd, check=False)
    return r.stdout if r.returncode == 0 else None


def skill_dirs(ref, cwd=None):
    """Set of folders that contain a SKILL.md at ref."""
    out = git("ls-tree", "-r", "-z", "--name-only", ref, cwd=cwd).stdout
    return {p[: -len("/SKILL.md")] for p in out.split("\0") if p.endswith("/SKILL.md")}


def owning_skill(path, dirs):
    """Nearest ancestor folder of `path` that is a skill folder, or None."""
    parts = path.split("/")
    for i in range(len(parts), 0, -1):
        cand = "/".join(parts[:i])
        if cand in dirs:
            return cand
    return None


def parse_frontmatter(text):
    """Return the frontmatter dict. Raises ValueError with a readable message."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    m = re.match(r"^---\n(.*?)\n---[ \t]*(\n|$)", text, re.S)
    if not m:
        raise ValueError("missing frontmatter (file must start with --- and close with ---)")
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML in frontmatter: {e}") from None
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a mapping")
    return data


def version_of(fm):
    meta = fm.get("metadata")
    if not isinstance(meta, dict):
        return None
    v = meta.get("version")
    return str(v).strip() if v is not None else None


def semver(v):
    m = SEMVER_RE.match(v or "")
    return tuple(int(x) for x in m.groups()) if m else None


def check_skill(folder, fm):
    """Validate one skill's frontmatter. Returns (errors, warnings)."""
    errors, warnings = [], []
    extra = sorted(set(fm) - ALLOWED_TOP)
    if extra:
        errors.append(f"non-standard top-level fields {extra}: move them under metadata")
    name = fm.get("name")
    leaf = folder.rsplit("/", 1)[-1]
    if not isinstance(name, str) or not name:
        errors.append("name is required")
    else:
        if name != leaf:
            errors.append(f"name '{name}' must equal folder name '{leaf}'")
        if not NAME_RE.match(name):
            errors.append(f"name '{name}' must be lowercase letters, digits and single dashes")
        if len(name) > MAX_NAME:
            errors.append(f"name '{name}' is {len(name)} chars; max {MAX_NAME}")
    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errors.append("description is required")
    meta = fm.get("metadata")
    if not isinstance(meta, dict):
        errors.append("metadata block is required (with version)")
        return errors, warnings
    ver = version_of(fm)
    if not semver(ver):
        errors.append(f"metadata.version '{ver}' must be major.minor.patch")
    lc = meta.get("lifecycle")
    if lc is not None and lc not in LIFECYCLES:
        errors.append(f"metadata.lifecycle '{lc}' must be one of {sorted(LIFECYCLES)}")
    if lc == "deprecated" and not (meta.get("replaced_by") or meta.get("sunset")):
        warnings.append("lifecycle is deprecated: add metadata.replaced_by or metadata.sunset")
    return errors, warnings


def tag_name(name, version):
    return f"{name}--v{version}"
