# Releasing spectra-cli to PyPI

## One-time setup
1. Create PyPI account and a project name (e.g. `spectra-cli`).
2. Create an API token at PyPI: Account Settings → API tokens.
3. Store the token securely:
   - Locally (for manual upload): create `~/.pypirc`:
     ```ini
     [distutils]
     index-servers = pypi

     [pypi]
     repository = https://upload.pypi.org/legacy/
     username = __token__
     password = pypi-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
     ```
   - Or in GitHub Actions as `PYPI_API_TOKEN` (recommended if you add CI).

## Cut a release
1. Bump version in `pyproject.toml` and `spectra/__init__.py` (done).
2. Build the distribution:
   ```bash
   python -m pip install --upgrade build twine
   python -m build
   ```
   This creates files in `dist/`.
3. Upload to PyPI:
   ```bash
   twine upload dist/*
   ```
4. Users install globally via pipx:
   ```bash
   pipx install spectra-cli
   spectra init
   ```

## Optional: GitHub Actions publish
- Add a workflow that builds on a tag `v*` and uploads with `PYPI_API_TOKEN`.




