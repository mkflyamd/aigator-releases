# Contributing to AI Gator

## Filing Issues

Use GitHub Issues for bugs and feature requests. Include your OS version, Python version, and steps to reproduce.

## Submitting Pull Requests

1. Fork the repo and create a branch from `main`
2. Make your changes with tests where applicable
3. Open a PR against `main` on this repo

**Note:** PRs are reviewed and tested internally before they appear in `main`. We'll comment on your PR with feedback or merge status. This process usually takes a few days.

## Code Style

- Python: follow existing patterns, no type annotation required but welcome
- No `Co-Authored-By` lines in commit messages
- Keep commits focused — one logical change per commit

## Running Tests

```bash
pip install -r web/requirements.txt
python -m pytest tests/ -v
```
