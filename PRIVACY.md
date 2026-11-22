# AI Gator Privacy Policy

Effective date: 2026-11-22

AI Gator ("the app") is a desktop AI assistant that runs on your computer. This policy explains what the app stores on your device, what it sends elsewhere, and the choices you have. "We" means [LEGAL ENTITY NAME], the publisher of AI Gator.

## The short version

- AI Gator runs locally. We do not operate a server that receives your prompts, files, messages or credentials.
- We do not collect usage analytics, crash reports or advertising data from the app.
- Your prompts and the content the assistant reads go to the AI provider you configure. That provider's privacy terms apply to that data.
- The app acts on Microsoft 365, Slack, Jira, Confluence, GitHub and other services only with credentials you provide, and it never sends an email, Teams or Slack message, or calendar change without your approval.

## What the app stores on your device

Everything below stays on your computer unless the "What leaves your device" section says otherwise.

| Data                                                                                                | Where                                                                                                            | Notes                                                                                                                                                   |
| --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Sign-in tokens for Microsoft 365, Teams and Slack, and Jira, Confluence and GitHub access tokens    | `~/.gator/secrets/`                                                                                              | Encrypted with Windows DPAPI, or on macOS and Linux with a key held in the operating system's credential vault.                                         |
| AI provider settings, including the API key you enter                                               | `config.json` in `~/.gator`                                                                                      | Stored as readable text in your user profile folder. Protect that folder as you would any file holding a password.                                      |
| Task history: your prompts and the assistant's results                                              | `tasks.db` in `~/.gator`                                                                                         | Readable only by your user account. Kept until you delete it.                                                                                           |
| Short usage counters: first 100 characters of each prompt, token counts, tool names and error codes | the same database                                                                                                | Used to show your own usage. Counters older than 30 days or beyond 100,000 rows are removed automatically.                                              |
| Active conversation                                                                                 | memory only                                                                                                      | Not written to disk. The last 20 turns are kept while the app runs. You can clear a conversation from the app.                                          |
| Pinned contexts                                                                                     | `~/.config/gator/pinned_contexts.json`                                                                           | Stored as readable text.                                                                                                                                |
| Application logs                                                                                    | `%LOCALAPPDATA%\AIGator\logs` (Windows), `~/Library/Logs/AIGator` (macOS), `~/.local/state/AIGator/logs` (Linux) | Kept for 30 days up to 5 MB. Privacy mode, on by default in installed builds, removes file paths and tool names from logs. Secrets are always scrubbed. |
| Speech-to-text models                                                                               | `~/.gator/models/dictation`                                                                                      | Used for local dictation.                                                                                                                               |

Because these files live on your device, you can inspect or delete them at any time. Deleting `~/.gator` removes the app's stored data and sign-ins.

## What leaves your device

**Your AI provider.** When you send a request, the app sends your prompt, the recent conversation, and any files, web pages, emails or other content the assistant reads to complete the task, to the AI provider endpoint you configured. By default this is Anthropic (`api.anthropic.com`). If you configure a company gateway or another provider, the data goes there instead. If a gateway is configured, the app also sends your API key header and a user identifier with each request. We do not receive this data. The provider's terms and privacy policy govern how it is used.

**Services you connect.** When you ask the assistant to work with Microsoft 365 (Outlook, Calendar, Teams, OneDrive, OneNote, SharePoint), Slack, Jira, Confluence, GitHub, a website through the built-in browser agent, or an MCP server you added, the app calls those services with your credentials and sends what you ask it to send. Their terms and privacy policies apply. Content read from these services is also sent to your AI provider so the assistant can use it.

**Update checks.** The app checks GitHub once a day by default for a new release. GitHub receives your IP address and the request itself. The app sends no identifier of its own. Installers are verified against a published checksum before they run.

**Speech.** Dictation runs on your device. Audio is not sent anywhere.

**Analytics.** The app does not send analytics, crash reports or usage statistics to us or to any analytics service. The browser automation library the app uses has its own analytics switched off.

## Your approval and your control

The assistant prepares drafts of emails, Teams and Slack messages, Jira changes and calendar updates. Nothing is sent until you approve it. Each draft shows what data it contains and where it will go. Your administrator may add rules that block some data flows.

You decide which accounts to connect, which AI provider to use, and which folders and tools the assistant may access. You can disconnect an account or delete its stored token at any time.

## Retention and deletion

We hold none of your data, so there is nothing for us to delete. Data on your device stays until you remove it. Task history has no automatic expiry. To remove it, delete `tasks.db` or the `~/.gator` folder. Data sent to your AI provider or a connected service is kept under that provider's or service's policy, so make any deletion request to them.

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
