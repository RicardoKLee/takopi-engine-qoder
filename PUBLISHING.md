# Publishing to PyPI

See [takopi-engine-cursor/PUBLISHING.md](https://github.com/RicardoKLee/takopi-engine-cursor/blob/master/PUBLISHING.md) for the full release guide.

Quick links for this package:

- PyPI Trusted Publisher: https://pypi.org/manage/project/takopi-engine-qoder/settings/publishing/
- GitHub workflow: `.github/workflows/publish.yml`
- Release: `git tag vX.Y.Z && git push origin vX.Y.Z` (version must match `pyproject.toml`)

Trusted Publisher fields:

| Field | Value |
|-------|-------|
| Owner | `RicardoKLee` |
| Repository | `takopi-engine-qoder` |
| Workflow | `publish.yml` |
| Environment | `pypi` |
