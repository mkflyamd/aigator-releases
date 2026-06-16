# tests/mcp/fixtures/mcp_snippets.py
"""Real-world MCP config snippets used across test files. One constant per real README format."""

# Format 1: mcpServers + command  (Claude Desktop / Cursor stdio)
PLAYWRIGHT_MCPSERVERS_COMMAND = '{"mcpServers":{"playwright":{"command":"npx","args":["@playwright/mcp@latest"]}}}'
PLAYWRIGHT_MCPSERVERS_COMMAND_WITH_ENV = """{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"],
      "env": {"PWTEST_SCREENSHOT": "on"}
    }
  }
}"""
FILESYSTEM_MCPSERVERS_COMMAND = '{"mcpServers":{"filesystem":{"command":"npx","args":["@modelcontextprotocol/server-filesystem","/tmp"]}}}'

# Format 2: mcpServers + url  (Cursor HTTP)
CONDUCTOR_MCPSERVERS_URL = '{"mcpServers":{"conductor-mcp":{"url":"https://mcp-platform.amd.com/mcp/conductor_mcp"}}}'
GITHUB_MCPSERVERS_URL = '{"mcpServers":{"github":{"url":"https://api.githubcopilot.com/mcp/"}}}'

# Format 3: mcpServers + type:"http"  (Claude Code)
CONDUCTOR_CLAUDE_CODE = '{"mcpServers":{"conductor-mcp":{"type":"http","url":"https://mcp-platform.amd.com/mcp/conductor_mcp"}}}'
GITHUB_CLAUDE_CODE = '{"mcpServers":{"github":{"type":"http","url":"https://api.githubcopilot.com/mcp/"}}}'

# Format 4: servers key  (VS Code)
CONDUCTOR_VSCODE = '{"servers":{"conductor-mcp":{"url":"https://mcp-platform.amd.com/mcp/conductor_mcp"}}}'
GITHUB_VSCODE = '{"servers":{"github":{"url":"https://api.githubcopilot.com/mcp/"}}}'

# Format 5: remotes array  (MCP registry schema)
CONDUCTOR_REGISTRY = """{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "com.amd/conductor-mcp",
  "title": "Conductor MCP",
  "remotes": [{"type": "streamable-http", "url": "https://mcp-platform.amd.com/mcp/conductor_mcp"}]
}"""

# Format 6: bare server object, stdio  (README inner-object copy)
PLAYWRIGHT_BARE_OBJECT = '{"command":"npx","args":["@playwright/mcp@latest"]}'
FILESYSTEM_BARE_OBJECT = '{"command":"npx","args":["@modelcontextprotocol/server-filesystem","/tmp"]}'

# Format 7: bare URL object  (remote)
CONDUCTOR_BARE_URL_OBJECT = '{"url":"https://mcp-platform.amd.com/mcp/conductor_mcp"}'

# TOML  (Codex)
CONDUCTOR_TOML = '[mcp_servers.conductor-mcp]\nurl = "https://mcp-platform.amd.com/mcp/conductor_mcp"'
MULTI_TOML = '[mcp_servers.conductor]\nurl = "https://mcp-platform.amd.com/mcp/conductor_mcp"\n\n[mcp_servers.github]\nurl = "https://api.githubcopilot.com/mcp/"'

# Bare command lines
PLAYWRIGHT_COMMAND = 'npx @playwright/mcp@latest'
FETCH_COMMAND = 'uvx mcp-server-fetch'
PYTHON_COMMAND = 'python -m my_mcp_server --port 8080'

# Bare URLs
CONDUCTOR_URL = 'https://mcp-platform.amd.com/mcp/conductor_mcp'
GITHUB_API_URL = 'https://api.githubcopilot.com/mcp/'

# Multi-server (chooser path)
MULTI_SERVER_COMMAND = '{"mcpServers":{"playwright":{"command":"npx","args":["@playwright/mcp@latest"]},"filesystem":{"command":"npx","args":["@modelcontextprotocol/server-filesystem","/tmp"]}}}'

# Failure cases
EMPTY = ''
WHITESPACE = '   \n  '
GARBAGE = 'not json not toml not a url at all'
PARTIAL_JSON = '{"mcpServers":{'
MISSING_COMMAND = '{"mcpServers":{"x":{"args":["foo"]}}}'
MCPSERVERS_NULL = '{"mcpServers":null}'
EMPTY_STRING_COMMAND = '{"mcpServers":{"x":{"command":"","args":["foo"]}}}'
