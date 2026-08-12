# AI Gator

An AI-powered productivity assistant that lives in your taskbar. Chat with your calendar, email, Teams, files, Confluence, Jira, GitHub, and more, all from one sidebar.

![AI Gator screenshot](docs/images/aigator-screenshot.png)

---

## Install

Download the package for your platform from [GitHub Releases](https://github.com/mkflyamd/aigator-releases/releases):

- Windows x64: `AI-Gator-*-Windows-x64.exe`
- macOS Intel: `AI-Gator-*-macOS-x64.dmg`
- macOS Apple silicon: `AI-Gator-*-macOS-arm64.dmg`
- Linux x64: `AI-Gator-*-Linux-x64.AppImage` or the `.deb` package

Release packages include Electron and the AI Gator backend. You do not need to install Electron, Node.js, or Python. Current alpha packages are unsigned, so Windows SmartScreen or macOS Gatekeeper may display a warning.

### Single-line installers (coming soon)

The PowerShell and shell-based installers are temporarily unavailable. For now, use a package from GitHub Releases or follow the [development and build guide](docs/BUILD_INSTRUCTIONS.md) to run AI Gator from source.

---

## Features

- **Chat with your tools**: Outlook, Teams, Calendar, OneDrive, OneNote, SharePoint, Confluence, Jira, GitHub, and Slack
- **Skill marketplace**: install supported skills and plugins
- **Browser agent**: automate web tasks through natural language
- **MCP support**: connect Model Context Protocol servers
- **Multi-tab conversations**: work in parallel with different pinned contexts
- **Scheduler**: create recurring tasks and reminders

---

## Configuration

AI Gator supports direct Anthropic access and compatible corporate LLM gateways. See the [gateway setup guide](docs/gateway-setup.md) for configuration options.

Service integrations may require separate authentication or organization-managed permissions.

---

## Development and source builds

Developers need `uv`, Node.js 22+, and Windows 10/11, macOS, or a Linux desktop.

See the [development and build guide](docs/BUILD_INSTRUCTIONS.md) for the authoritative instructions covering:

- development setup and launch commands
- native package builds
- package smoke testing
- automated releases
- signing and troubleshooting

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

Apache 2.0, see [LICENSE](LICENSE).
