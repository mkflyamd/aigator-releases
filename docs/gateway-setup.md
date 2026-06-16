# Gateway Setup

AI Gator routes all LLM requests through `web/llm/gateway.py`. Configure it in `~/.config/teamspoc/config.json`.

---

## Option 1: Direct Anthropic (default)

Get an API key at [console.anthropic.com](https://console.anthropic.com).

```json
{
  "api_key": "sk-ant-...",
  "llm_gateway_url": "https://api.anthropic.com"
}
```

No additional headers needed. The Anthropic SDK handles auth via the `api_key` field.

---

## Option 2: Corporate LLM Gateway

If your organization runs a proxy in front of the Anthropic API (common in enterprises for usage tracking, cost allocation, and compliance):

```json
{
  "api_key": "your-gateway-subscription-key",
  "llm_gateway_url": "https://llm.your-company.com/Anthropic",
  "llm_gateway_key_header": "Ocp-Apim-Subscription-Key",
  "llm_gateway_user_field": "user",
  "gateway_user_id": "your-user-id"
}
```

| Field | Description |
|---|---|
| `llm_gateway_url` | Base URL of your gateway |
| `llm_gateway_key_header` | Header name your gateway expects for the API key |
| `llm_gateway_user_field` | Header name for per-user tracking (optional) |
| `gateway_user_id` | Your user identifier for that header |

Contact your gateway administrator for the correct values.

---

## Environment Variables

All config values can also be set as env vars (useful for CI or Docker):

| Env var | Config key equivalent |
|---|---|
| `ANTHROPIC_API_KEY` | `api_key` |
| `LLM_GATEWAY_URL` | `llm_gateway_url` |
| `GATEWAY_KEY_HEADER` | `llm_gateway_key_header` |
| `GATEWAY_USER_FIELD` | `llm_gateway_user_field` |
| `GATEWAY_USER_ID` | `gateway_user_id` |

Env vars take precedence over `config.json` values.
