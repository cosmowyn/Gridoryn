# Release Checklist

Use this checklist before cutting a public stable release.

## Metadata and docs

- Confirm [app_metadata.py](../app_metadata.py) version matches the intended release.
- Confirm [CHANGELOG.md](../CHANGELOG.md) has a complete release entry.
- Confirm [README.md](../README.md) install/build instructions still match the real workflow.
- Regenerate screenshots with:
  - `./.venv/bin/python scripts/generate_release_screenshots.py`

## Quality gates

- Run:
  - `./.venv/bin/python -m pytest -q`
  - `python3 -m py_compile *.py tests/*.py`
- Launch the app once locally and verify:
  - startup succeeds
  - help opens
  - demo workspace loads
  - backup/snapshot flows still work
  - project cockpit and relationship inspector update on selection changes

## Build

- Ensure `build/` and `dist/` are cleared or disposable.
- Run:
  - `./.venv/bin/python buildfile.py`
- Verify:
  - the built artifact exists under `dist/`
  - a versioned release copy exists under `dist/release/`
  - `dist/release_manifest.json` was written
  - the build used the intended icon/splash assets or environment overrides

## Distribution safety

- Confirm no local signing material is being staged or packaged.
- Confirm the build output uses the stable product name `CustomToDo`.
- Confirm logs, screenshots, and demo data contain no private/personal sample data.
