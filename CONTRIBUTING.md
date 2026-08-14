# Contributing to AI Gator

Thank you for your interest in contributing to AI Gator!

---

## Contributor License Agreement (CLA)

Before we can accept your contribution, you must agree to the following CLA.
By submitting a pull request, opening an issue with a proposed fix, or otherwise
contributing code or content to this repository, **you agree to the terms below**.

### Individual CLA

You (the contributor) grant **the AI Gator project** a perpetual,
worldwide, non-exclusive, no-charge, royalty-free, irrevocable license to:

- reproduce, prepare derivative works of, publicly display, publicly perform,
  sublicense, and distribute your contributions and derivative works thereof
  under any license terms the project chooses, now or in the future

You retain ownership of your copyright. This agreement does not transfer your
copyright to the project — it grants the project the right to use your
contribution however the project requires, including under a different license
in a future version.

You represent that:

1. You are legally entitled to grant the above license.
2. Each contribution is your original creation, or you have the right to submit
   it under these terms.
3. Your contribution does not include confidential or proprietary information
   belonging to a third party.

If you are contributing on behalf of your employer, you represent that your
employer has authorized you to contribute on its behalf, or that your employer
has waived any rights it may have in your contributions.

---

## How to Contribute

### Reporting Bugs

Open an issue and include:

- A clear title and description
- Steps to reproduce
- What you expected vs. what happened
- OS version and AI Gator version

### Suggesting Features

Open an issue tagged `enhancement`. Describe the problem you want to solve,
not just the solution — this helps us understand the use case.

### Submitting a Pull Request

1. Fork the repository and create a branch from `main`.
2. Make your changes with clear, focused commits.
3. Test your changes locally.
4. Open a pull request with a description of what changed and why.
5. By opening the PR, you agree to the CLA above.

### Quality Checks

Install the commit, commit-message, and push hooks after cloning:

```bash
uv sync --locked
uv run pre-commit install --install-hooks
```

Commit-time hooks check only relevant changed files for whitespace, line endings,
structured-file validity, Python correctness, JavaScript syntax, shell issues,
PowerShell issues when PSScriptAnalyzer is installed, secrets, unsafe Python
patterns, and GitHub Actions security. Commit-message hooks reject messages that
contain potential secrets. Push-time hooks use `uv audit` to check all
locked Python dependencies and adverse package statuses, then run `npm audit` for
Electron dependencies. They fail on any known Python vulnerability or
high/critical npm vulnerability. CI also enables uv's malware check before syncing
locked dependencies. Run the same gates manually with:

```bash
uv run pre-commit run --all-files
uv run pre-commit run detect-secrets --hook-stage commit-msg --commit-msg-filename .git/COMMIT_EDITMSG
UV_PREVIEW_FEATURES=audit-command uv run pre-commit run --all-files --hook-stage pre-push
```

Enable malware checks during a local dependency sync with:

```bash
UV_MALWARE_CHECK=1 UV_PREVIEW_FEATURES=malware-check uv sync --locked
```

CI runs both commands on every pull request and push to `main`. It also runs
PSScriptAnalyzer on Windows, so install that module to reproduce PowerShell CI
locally. Update hooks with `uv run pre-commit autoupdate`, review the upstream
release notes, then run both commands before submitting the dependency update.

Secret findings must be removed. A false positive may be added to
`.secrets.baseline` only after manual review. Security scanner suppressions must
be narrowly scoped, include the scanner rule ID, and be justified in the pull
request. Dependency audit exceptions require a tracked security issue with an
owner, expiration date, and compensating controls.

### Code Style

- Python formatting and correctness checks use Ruff; security checks use Bandit
- JavaScript, CSS, HTML, JSON, YAML, and Markdown formatting uses Prettier
- Keep pull requests focused — one concern per PR

---

## Questions?

Open an issue or start a discussion in the repository.
