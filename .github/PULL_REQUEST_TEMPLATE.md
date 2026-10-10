## Summary

<!-- What changed and why. -->

## Security checklist

- [ ] Every new or changed POST/PUT/PATCH/DELETE route uses `dependencies=[Depends(verify_csrf)]` (`web/security.py`) and is not added to `tests/csrf_route_baseline.txt`.
- [ ] Every new route that sends, posts, creates, or deletes in an external app (email, Teams, Slack, Jira, calendar) is draft-only and needs explicit human approval through `/api/drafts/{id}/approve`. It never sends automatically.
- [ ] Every new LLM call goes through `llm.gateway`.
- [ ] Tests, examples, and docs use only the fake credential `aigator-fake-api-key`.
- [ ] Not applicable: this PR adds no routes, sends, or LLM calls.

## Test plan

<!-- How you checked the change. -->
