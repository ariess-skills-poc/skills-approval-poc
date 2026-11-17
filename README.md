# skills-approval-poc

Public test repo for a skill-library approval flow. **All content is fake.**

- `main` = published skills. Changes only via pull request.
- `CODEOWNERS` assigns each folder to a team; that team must approve.
- `validate` CI: frontmatter uses standard fields only, name = folder, name ≤ 40 chars, `metadata.version` is semver and bumped when a skill changes.
- `release` workflow: after merge, tags each new version as `<name>--v<version>`.
