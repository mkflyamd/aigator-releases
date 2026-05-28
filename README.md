# AI Gator

An AI-powered productivity assistant that lives in your taskbar. Chat with your calendar, email, Teams, files, Confluence, Jira, GitHub, and more — all from one sidebar.

![AI Gator screenshot](docs/images/aigator-screenshot.png)

---

## Quick Start (Developers)

**Requirements:** Python 3.12, Windows 10/11

```bash
git clone https://github.com/mkflyamd/aigator-releases.git
cd aigator-releases
pip install -r web/requirements.txt
```

Configure your API key:

```json
// ~/.config/teamspoc/config.json
{
  "api_key": "sk-ant-...",
  "llm_gateway_url": "https://api.anthropic.com"
}
```

Start the server:

```powershell
web\start.bat
```

Open `http://localhost:5000` in your browser.

---

## Features

- **Chat with your tools** — Outlook, Teams, Calendar, OneDrive, OneNote, SharePoint, Confluence, Jira, GitHub, Slack
- **Skill marketplace** — install community skills from any git repo
- **Browser agent** — automate web tasks via natural language
- **MCP support** — connect any Model Context Protocol server
- **Multi-tab** — run parallel conversations pinned to different contexts
- **Scheduler** — set up recurring tasks and reminders

---

## Configuration

See [docs/gateway-setup.md](docs/gateway-setup.md) for gateway configuration — direct Anthropic or corporate LLM proxy.

See [GETTING_STARTED.md](GETTING_STARTED.md) for full setup walkthrough.

---

## Enterprise Deployment

AI Gator works with any corporate LLM gateway that proxies the Anthropic API. Configure in `~/.config/teamspoc/config.json`:

```json
{
  "api_key": "your-gateway-key",
  "llm_gateway_url": "https://llm.your-company.com/Anthropic",
  "llm_gateway_key_header": "Ocp-Apim-Subscription-Key",
  "llm_gateway_user_field": "user",
  "gateway_user_id": "your-user-id"
}
```

M365 integration requires an Azure AD app registration with the permissions listed in [GETTING_STARTED.md](GETTING_STARTED.md).

For building a Windows installer, see [BUILD_INSTRUCTIONS.md](BUILD_INSTRUCTIONS.md).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
