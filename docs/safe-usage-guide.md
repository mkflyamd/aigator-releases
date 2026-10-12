# Safe Usage Guide: Moving Data Between Apps

Use this guide with AI Gator. It explains how to keep data in the right place.

## Before you approve a draft

AI Gator never sends an email, a Teams message, a Slack message, a Jira change or a calendar change by itself. It makes a draft. You approve it.

Read these parts of the draft card before you click approve:

1. **Data from.** This line lists the apps AI Gator read in this request (for example "Outlook mail"). If it lists an app you did not expect, do not approve.
2. **Sending to.** This line names the destination app. Check that the data is allowed to go there.
3. **Recipients and channel.** Check every name, address and channel. Check for people outside AMD.
4. **Sensitive content banner.** A yellow banner shows when the text contains a classification word (for example "Confidential" or "Internal Use Only"). The banner is a warning only. It does not know the real classification of the data. You decide.

## Rules

- Follow the AMD Data Classification Standard. Confidential data must not go to an external destination or to a tool that is not approved for it.
- Do not ask AI Gator to copy confidential email text into Jira, Confluence, Slack or GitHub unless that is allowed for that data.
- Use a new tab for each task. A tab only keeps the apps that you allowed in it.
- If a draft is wrong, do not approve it. Edit it or ask AI Gator to change it.
- If AI Gator says that your administrator blocks a data flow, do not look for another way. Ask your administrator.

## Browsers and browser extensions

AI Gator runs a local web server on your computer. Other programs on the computer, and web pages in your browser, can try to reach it. Follow these rules to keep it safe:

- Use AI Gator only in its own window. The installed app gives the page only to its own window. If you open the address (`http://127.0.0.1:8000/`) in an ordinary browser, you get an error. That is correct. Do not look for a way around it.
- Do not install a browser extension that you do not trust. An extension can read every page in the browser. A malicious extension can read data that you show in AI Gator if you open it in that browser.
- Do not open web pages from sources that you do not trust while you use AI Gator. AI Gator refuses a state-changing request that does not come from its own page (it checks the origin of the request and a token that is tied to the page address), but a clean browser profile is the safest option.
- AI Gator shows interactive pages that the assistant makes (widgets) in a frame inside the page. Widgets can run scripts. Do not type passwords or keys into a widget. A widget cannot load scripts from other web sites, and it cannot send data to other web sites with a script request.
- If you see a page that asks you to approve something that you did not ask for, close it and tell your administrator.

## For administrators

Administrators can block flows with `blocked_data_flows` in the admin policy file (see `docs/BUILD_INSTRUCTIONS.md`). `GET /api/sandbox/status` shows the policy that is in force on a device. Use it to audit the configuration.
