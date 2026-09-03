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

### Single-line installers

The installers identify the latest published release through the GitHub API, select the package for your operating system and architecture, verify it against `SHA256SUMS.txt` or the GitHub-provided SHA-256 asset digest, and log each download, verification, installation, and cleanup step.

**Windows x64 (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/mkflyamd/aigator-releases/main/Get-AIGator.ps1 | iex
```

**macOS Intel/Apple silicon or Linux x64:**

```bash
curl -fsSL https://raw.githubusercontent.com/mkflyamd/aigator-releases/main/Get-AIGator.sh | bash
```

Windows runs the interactive NSIS installer. macOS installs `AI Gator.app` under `~/Applications`. Linux installs the AppImage under `${XDG_DATA_HOME:-$HOME/.local/share}/ai-gator` and creates `${XDG_BIN_HOME:-$HOME/.local/bin}/ai-gator`. The Unix installer needs `curl` and a Python 3 interpreter on Linux; macOS can use its built-in JavaScript runtime when Python is unavailable.

To inspect a script before running it, download it from the repository and run it locally:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/mkflyamd/aigator-releases/main/Get-AIGator.ps1 -OutFile Get-AIGator.ps1
.\Get-AIGator.ps1
```

```bash
curl -fL https://raw.githubusercontent.com/mkflyamd/aigator-releases/main/Get-AIGator.sh -o Get-AIGator.sh
bash Get-AIGator.sh
```

Use `-KeepDownload` on Windows or `--keep-download` on macOS/Linux to retain downloaded files for troubleshooting. The Unix installer also supports `--no-launch`. To validate release selection, download, and checksum verification without installing or launching AI Gator, run the downloaded script with `-DryRun` on Windows or `--dry-run` on macOS/Linux.

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
