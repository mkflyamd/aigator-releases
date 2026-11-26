# AI Gator Privacy Policy

Effective date: 2026-11-22

AI Gator ("the app") is a desktop AI assistant that runs on your computer. This policy explains what the app stores on your device, what it sends elsewhere, and the choices you have. "We" means [LEGAL ENTITY NAME], the publisher of AI Gator.

## The short version

- AI Gator runs locally. We do not operate a server that receives your prompts, files, messages or credentials.
- We do not collect usage analytics, crash reports or advertising data from the app.
- Your prompts and the content the assistant reads go to the AI provider you configure. That provider's privacy terms apply to that data.
- The app acts on Microsoft 365, Slack, Jira, Confluence, GitHub and other services only with credentials you provide, and it never sends an email, Teams or Slack message, or an invitation to other people without your approval. Some actions on your own calendar, such as responding to an invitation, cancelling in supported cases, or adding an out-of-office entry, happen directly.

## What the app stores on your device

Everything below stays on your computer unless the "What leaves your device" section says otherwise.

| Data                                                                                                                               | Where                                                                                                                                                                                                                                                  | Notes                                                                                                                                                                                                                                                                                                                    |
| ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Sign-in tokens for Microsoft 365, Teams and Slack, and Jira, Confluence and GitHub access tokens                                   | `~/.gator/secrets/`                                                                                                                                                                                                                                    | Encrypted with Windows DPAPI. On macOS and Linux they are encrypted with a key held in the operating system's credential vault, or, on a Linux system without one, a key file in the same folder that only your user account can read.                                                                                   |
| AI provider settings, including the API key you enter                                                                              | `config.json` in `~/.gator`                                                                                                                                                                                                                            | Stored as readable text in your user profile folder. Protect that folder as you would any file holding a password.                                                                                                                                                                                                       |
| Task history: your prompts and the assistant's results                                                                             | `tasks.db` in `~/.gator`                                                                                                                                                                                                                               | Readable only by your user account. Kept until you delete it. This is not the full chat transcript; see "Chat tabs" below.                                                                                                                                                                                               |
| Usage log: the first 100 characters of each prompt and token counts                                                                | the same database                                                                                                                                                                                                                                      | Used to show your own usage. Kept until you delete the database.                                                                                                                                                                                                                                                         |
| Turn and tool-run records: outcome, token counts, tool names and error codes, never the content of your messages                   | the same database                                                                                                                                                                                                                                      | Records older than 30 days, or beyond 100,000 rows, are removed automatically.                                                                                                                                                                                                                                           |
| Active conversation (server side)                                                                                                  | memory only                                                                                                                                                                                                                                            | Not written to disk by the app. The most recent 20 turns are sent with each request. Discarded when you close the tab or quit the app.                                                                                                                                                                                   |
| Chat tabs: the open tabs, message history, the chat as displayed (including rendered message HTML and draft cards) and unsent text | The app's browser storage (`localStorage`) in the `gator-shell-8000` folder inside your application data folder: `%APPDATA%` (Windows), `~/Library/Application Support` (macOS), `~/.config` (Linux). The number is the backend port, 8000 by default. | Stored as readable text. Closing a chat tab removes that tab's saved data.                                                                                                                                                                                                                                               |
| Pinned contexts                                                                                                                    | `~/.config/gator/pinned_contexts.json`                                                                                                                                                                                                                 | Stored as readable text.                                                                                                                                                                                                                                                                                                 |
| Application logs                                                                                                                   | `%LOCALAPPDATA%\AIGator\logs` (Windows), `~/Library/Logs/AIGator` (macOS), `~/.local/state/AIGator/logs` (Linux)                                                                                                                                       | Two rotating files of up to 5 MB each. A log file that has not been written to for 30 days is removed, so individual entries in a file that is still being written can be older than 30 days. Privacy mode, on by default in installed builds, removes file paths and tool names from logs. Secrets are always scrubbed. |
| Speech-to-text models                                                                                                              | The default model is in the application's `resources/models/dictation` folder. Models you add are in `~/.gator/models/dictation`.                                                                                                                      | Used for local dictation.                                                                                                                                                                                                                                                                                                |

Because these files live on your device, you can inspect or delete them at any time. To remove all app data, quit the app and delete `~/.gator`, `~/.config/gator`, the `gator-shell-8000` folder described above (this also holds the sessions of web apps you opened in the app) and the logs folder. Deleting `~/.gator` alone leaves your saved chats and pinned contexts.

## What leaves your device

**Your AI provider.** When you send a request, the app sends your prompt, the recent conversation, and any files, web pages, emails or other content the assistant reads to complete the task, to the AI provider endpoint you configured. By default this is Anthropic (`api.anthropic.com`). If you configure a company gateway or another provider, the data goes there instead. If a gateway is configured, the app also sends your API key header and a user identifier with each request. We do not receive this data. The provider's terms and privacy policy govern how it is used.

**Services you connect.** When you ask the assistant to work with Microsoft 365 (Outlook, Calendar, Teams, OneDrive, OneNote, SharePoint), Slack, Jira, Confluence, GitHub, a website through the built-in browser agent, or an MCP server you added, the app calls those services with your credentials and sends what you ask it to send. Their terms and privacy policies apply. Content read from these services is also sent to your AI provider so the assistant can use it.

**Update checks.** The app checks GitHub once a day by default for a new release. GitHub receives your IP address and the request itself. The app sends no identifier of its own. Installers are verified against a published checksum before they run.

**Speech.** Dictation runs on your device. Audio is not sent anywhere.

**Analytics.** The app does not send analytics, crash reports or usage statistics to us or to any analytics service. The browser automation library the app uses has its own analytics switched off.

## Your approval and your control

The assistant prepares drafts of emails, Teams and Slack messages, Jira changes and invitations to other people. None of these is sent until you approve it. Each draft shows what data it contains and where it will go. Some actions on your own account, such as adding an out-of-office entry to your own calendar, happen directly without invitees. Your administrator may add rules that block some data flows.

You decide which accounts to connect, which AI provider to use, and which folders and tools the assistant may access. You can disconnect an account or delete its stored token at any time.

## Retention and deletion

We hold none of your data, so there is nothing for us to delete. Data on your device stays until you remove it. Task history has no automatic expiry. To remove it, delete `tasks.db`, and delete saved chats as described under "What the app stores on your device". Data sent to your AI provider or a connected service is kept under that provider's or service's policy, so make any deletion request to them.

## Sensitive and work data

If you use AI Gator with data from your employer or another organisation, you are responsible for following their rules about what may be shared with an AI provider. Choose a provider and gateway your organisation permits.

## Children

AI Gator is not directed to children under 16 and we do not knowingly collect data from them.

## Your rights

Because we do not collect or hold your personal data, the controls above are how you access, correct or delete it. If you believe we hold personal data about you, for example from correspondence, email us at [CONTACT EMAIL] and we will respond within 30 days.

## Changes

If we change how the app handles data, for example by adding usage reporting, we will update this policy, show the change in the release notes, and not apply it to existing installs without your opt-in where the law requires it. The effective date above shows the latest version.

## Contact

[LEGAL ENTITY NAME], [POSTAL ADDRESS], [CONTACT EMAIL]
