# Releasing governai

## One-time setup

1. Add your remote:
   ```bash
   git remote add origin git@github.com:rrrozhd/governai.git
   ```
2. Configure a PyPI Trusted Publisher for:
   - repository: `rrrozhd/governai`
   - workflow: `publish.yml`
   - environment: `pypi`
3. Ensure the repository default branch is `main`.

## Local pre-release check

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m build
python -m twine check dist/*
```

## Cut a release

1. Update `version` in `pyproject.toml`.
2. Commit the version bump.
3. Tag the release using the same version:
   ```bash
   git tag vX.Y.Z
   ```
4. Push branch and tags:
   ```bash
   git push origin main --tags
   ```

The `Publish Package` workflow runs on `v*` tags and uploads to PyPI through GitHub OIDC trusted publishing.

## Publish on Git only (without PyPI)

If you only want source publish on your git host:

```bash
git push origin main
```

Consumers can install directly:

```bash
pip install "governai @ git+https://github.com/rrrozhd/governai.git@main"
```
