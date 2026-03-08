# Contributing

Thanks for contributing to CustomToDo.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
```

Run the application locally with:

```bash
python main.py
```

## Development Expectations

- Keep changes pragmatic and reviewable
- Preserve existing user-facing behavior unless the change explicitly fixes a bug or improves documented UX
- Reuse existing patterns before introducing new abstractions
- Follow existing Python style conventions and keep code close to PEP 8 where practical without introducing risky non-functional churn
- Update help text and repository docs when behavior changes in a user-visible way
- Keep desktop behavior cross-platform where practical, with Windows and macOS as the main targets

## Validation

At minimum, run:

```bash
python -m py_compile *.py
python -m pytest -q
```

If your change touches UI code, also perform a manual smoke test of the affected windows, dialogs, and workflows.

## Reporting Bugs

When filing a bug report, include:

- platform and Python version
- steps to reproduce
- expected behavior
- actual behavior
- screenshots or console output when relevant
- whether the issue affects packaged builds, development runs, or both

## Submitting Changes

- Keep pull requests focused
- Explain the user-facing impact and any migration or data implications
- Note any limitations or follow-up work honestly
- Avoid mixing unrelated refactors with behavior changes
