# Releasing governai

## One-time setup

1. Add your remote:
   ```bash
   git remote add origin git@github.com:rrrozhd/governai.git
   ```
2. In GitHub repository settings, add secret `PYPI_API_TOKEN`.
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
   git tag v0.2.0
   ```
4. Push branch and tags:
   ```bash
   git push origin main --tags
   ```

The `Publish Package` workflow runs on `v*` tags and uploads to PyPI.

## Publish on Git only (without PyPI)

If you only want source publish on your git host:

```bash
git push origin main
```

Consumers can install directly:

```bash
pip install "governai @ git+https://github.com/rrrozhd/governai.git@main"
```
