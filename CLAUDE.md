# AI Gator — Development Guidelines

## LLM Gateway

All LLM calls must go through `llm.gateway` — never construct headers or URLs inline.
Configure your gateway in `config.json` (see `docs/gateway-setup.md`).

### How to add a new LLM call site

```python
# For browser-use ChatAnthropic:
from llm.gateway import create_gateway_chat_anthropic
llm = create_gateway_chat_anthropic(model, api_key, base_url)

# For raw Anthropic SDK client:
from llm.gateway import gateway_headers, get_gateway_url
client = anthropic.Anthropic(
    api_key=api_key,
    base_url=get_gateway_url(),
    default_headers=gateway_headers(api_key),
)
```

## Git Commits

Do not add `Co-Authored-By` lines in commit messages.

## Naming

This project is called **AI Gator** — never refer to it as a POC.

## Human-in-the-Loop

Email, Teams, and Slack messages must NEVER auto-send. Always draft-only and require explicit human approval before sending.
