---
name: github
description: "GitHub Enterprise — issues, pull requests, code review."
metadata:
  author: Mayuresh Kulkarni
  version: "1.0"
  format: agentskills-1.0
---

# GitHub Rules

- NEVER create an issue or PR without showing a compose form and waiting for explicit user confirmation.
- NEVER merge a pull request without stating the exact source branch, target branch, and merge strategy, and receiving explicit confirmation.
- NEVER push or modify code files directly.
- ALWAYS show repositories as org/repo format (e.g. rocm/rocm, not just rocm).
- If the target repository is ambiguous, ask the user which org/repo before proceeding.
- When showing PR details, always include CI check status and reviewer state.
- Use relative time ("2 days ago", "1d") not absolute dates.
- For "what needs my review" → call github_list_review_requests.
- For "my issues" → call github_list_my_issues.
- For "my PRs" → call github_list_my_prs.
- For issue or PR details, parse owner/repo/number from URLs or ask the user if missing.
