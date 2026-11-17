# skills-approval-poc

Public test repo for a skill-library approval flow. **All content is fake.**
Reusable as a template: copy `.github/` and `CODEOWNERS`.

## Flow
- `main` = published skills. Changes only via pull request.
- `CODEOWNERS` assigns each folder to a team; that team must approve (last matching line wins).
- `validate` (on PR) must pass. `release` (on push to main) tags new versions as `<name>--v<version>`.

## What `validate` checks (`.github/scripts/validate.py`)
- A skill is "touched" if any file in its folder changed (SKILL.md, scripts/, references/, assets/), incl. renames and deletions.
- Frontmatter parsed with PyYAML (quotes, comments, CRLF, block scalars OK).
- Only standard top-level fields: name, description, license, compatibility, allowed-tools, metadata.
- `name` = folder name, lowercase-dash, ≤ 40 chars; names unique in the repo.
- `metadata.version` is major.minor.patch and strictly higher than on the base branch for every touched skill.
- Optional `metadata.lifecycle`: experimental | stable | deprecated | retired (deprecated → warn without `replaced_by`/`sunset`).
- Deleted skills pass with a notice. A missing base ref fails.

## What `release` does (`.github/scripts/release.py`)
- Tags only skills whose version changed in the push; first push tags all untagged skills.
- Never re-tags; fails if a version's tag already exists on another commit. Tag message includes the PR number.
- Serialized with a `concurrency` group.

## Required repo settings
- Ruleset on `main`: PR required, code-owner review, status check `validate`, no admin bypass.
- **Tag ruleset on `*--v*`**: restrict create/update/delete; only the release workflow's identity may bypass. Otherwise anyone with write access can tag an unreviewed commit as a release.

## Tests
`pip install pyyaml==6.0.2 && python3 -m unittest discover -s .github/scripts`
