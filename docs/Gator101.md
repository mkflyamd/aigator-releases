# AI Gator 101 -- How It Works

## The Big Picture

AI Gator is a **personal AI assistant** that connects to your work tools -- Outlook, Teams, Slack, Calendar, Jira, OneDrive, etc. -- and lets you interact with all of them through a single chat interface, like having a smart coworker who can check your email, schedule meetings, and create documents for you.

It's a **web app** -- you open it in a browser, type a message, and the AI responds.

---

## File Types -- What Does What

| File type | Language | Where it runs | What it does |
|-----------|----------|--------------|--------------|
| `.py` (Python) | Python | **Server** (your computer) | The backend brain -- talks to AI, calls Microsoft/Slack APIs, processes data |
| `.js` (JavaScript) | JavaScript | **Browser** (Chrome/Edge) | The frontend face -- what you see, type into, click on |
| `.html` | HTML | **Browser** | The page structure -- buttons, text areas, panels |
| `.css` | CSS | **Browser** | The styling -- colors, fonts, layouts, animations |
| `.md` (Markdown) | Markdown | **Server** (read by AI) | Instructions that tell the AI how to behave for each skill |

Think of it like a restaurant:
- **HTML/CSS** = the dining room (what customers see)
- **JavaScript** = the waiter (takes your order, brings food back)
- **Python** = the kitchen (does the actual cooking)
- **Markdown** = the recipe book (tells the chef how to make each dish)

---

## Folder Structure

```
web/
  app.py                 <- The main server file (starts everything)
  shared.py              <- Shared state (loaded tools, config, globals)
  config.py              <- Reads/saves settings from config.json

  routes/                <- URL handlers (one file per feature area)
    chat.py              <-   /api/chat -- the main AI conversation endpoint
    email.py             <-   /api/email/* -- inbox sidebar data
    teams.py             <-   /api/teams/* -- Teams sidebar data
    calendar.py          <-   /api/calendar/* -- calendar view data
    config_routes.py     <-   /api/config/* -- settings page
    ...

  llm/                   <- AI model abstraction layer
    base.py              <-   Defines the interface any AI provider must follow
    registry.py          <-   Which models are available, which is active
    anthropic_provider.py <-  Talks to Claude (the specific AI we use)

  skills/                <- One folder per capability
    email/
      tools.py           <-   Functions: read_email(), search_email(), reply_email()
      SKILL.md           <-   Instructions for AI: "when user asks about email, do this..."
    calendar/
      tools.py           <-   Functions: check_availability(), create_meeting()
      SKILL.md
    teams/
    slack/
    jira/
    ...

  static/                <- Frontend files (sent to the browser)
    index.html           <-   The single HTML page
    app.js               <-   Main UI logic (chat, sidebar, sending messages)
    third-pane.js        <-   Right panel (compose email, create Jira ticket)
    style.css            <-   All the visual styling
```

---

## End-to-End Example: "Check my inbox"

Here's exactly what happens when you type **"Check my inbox"** and press Enter:

### Step 1: Browser (JavaScript)

```
You type "Check my inbox" -> press Enter
```

`app.js` catches the form submit:
1. Shows your message in a chat bubble
2. Creates an empty assistant bubble with "Gator is on it..."
3. Sends a **POST request** to `http://localhost:8000/api/chat` with:
   ```json
   {
     "message": "Check my inbox",
     "history": ["...previous messages..."],
     "active_skills": ["email"],
     "context_id": "tab-abc123"
   }
   ```

### Step 2: Server receives the request (Python)

`routes/chat.py` receives the POST request:

1. **Builds the system prompt** -- a giant instruction set telling the AI who it is, what skills are active, what tools it can use. Think of it as a briefing document.

2. **Auto-detects skills** -- your message contains "inbox" which matches the email keyword list. If no keywords match, a fast AI call (Haiku) classifies the intent.

3. **Filters tools** -- only gives the AI tools for active skills. If email is active, the AI gets `read_email`, `search_email`, `reply_email`, etc. It does NOT get calendar or Jira tools.

### Step 3: AI decides what to do (Claude API)

The server calls Claude (the AI) with:
- The system prompt ("You are Gator, a helpful assistant...")
- The user's message ("Check my inbox")
- The available tools (email tools)

Claude's response comes back **streaming** (word by word):
```
"Let me check your inbox..."  [streams to browser as it generates]
```

Then Claude says: "I want to call the `read_email` tool."

### Step 4: Tool execution (Python)

The server sees Claude wants to call `read_email`. It:

1. Yields a **status event** -- browser shows "Checking email..."
2. Calls `execute_tool("read_email", {"count": 10})`
3. This runs the `_tool_read_email()` function in `skills/email/tools.py`
4. That function calls the **Microsoft Graph API** (Microsoft's backend) to fetch your actual emails
5. Returns a list of emails as a Python dict

### Step 5: AI processes the results (Claude API)

The server feeds the email data back to Claude:
```json
{"emails": [
  {"subject": "Q3 Budget Review", "from": "Sarah", "preview": "..."},
  {"subject": "Lunch tomorrow?", "from": "Mike", "preview": "..."}
]}
```

Claude reads the data and generates a human-friendly summary:
```
"You have 2 unread emails:
 1. Q3 Budget Review from Sarah -- about the budget deck...
 2. Lunch tomorrow? from Mike -- asking about lunch plans..."
```

This streams to the browser token by token.

### Step 6: Browser renders the response (JavaScript)

`app.js` receives the streamed tokens via **SSE (Server-Sent Events)** -- a one-way pipe from server to browser:

```
data: {"status": "Checking email..."}     -> shows status line
data: {"token": "You"}                    -> starts building response
data: {"token": " have"}                  -> adds to response
data: {"token": " 2 unread"}              -> keeps building...
...
data: {"usage": {"input_tokens": 1500}}   -> updates token meter
data: [DONE]                              -> stops, removes cursor
```

Each token triggers a re-render of the markdown text in the chat bubble.

### The Visual Result

```
+------------------------------------------+
| You                                       |
|   Check my inbox                         |
+------------------------------------------+
| Gator                                     |
|   * Checking email...                    |
|  ----------------------------------------|
|  You have 2 unread emails:              |
|  1. **Q3 Budget Review** from Sarah     |
|  2. **Lunch tomorrow?** from Mike       |
+------------------------------------------+
```

---

## The Agentic Loop -- What Makes It "Smart"

The key difference between Gator and a simple chatbot: **it can take actions in a loop**.

```
User: "Reply to Sarah's email saying I'll review it tomorrow,
       then block 2pm on my calendar for the review"

Loop iteration 1:
  AI thinks -> "I need to reply to Sarah's email"
  AI calls  -> reply_email(message_id="...", body="I'll review it tomorrow")
  Result    -> draft created, approval card shown to user

Loop iteration 2:
  AI thinks -> "Now I need to create a calendar event"
  AI calls  -> create_event(subject="Budget Review", start="2pm", ...)
  Result    -> event created

Loop iteration 3:
  AI thinks -> "Both tasks done, let me summarize"
  AI responds -> "Done! Drafted a reply to Sarah and blocked 2pm for the review."
```

The AI keeps looping (up to 8 times) until it decides it's done. Each loop can call different tools, across different skills, in parallel.

---

## Key Design Principles

1. **Human-in-the-loop** -- The AI never sends emails/messages directly. It creates drafts and shows you an "Approve" button.

2. **Skill-based** -- Each capability (email, calendar, Jira) is a self-contained skill folder. Adding a new skill = adding one folder with `tools.py` + `SKILL.md`.

3. **Provider-agnostic** -- The AI layer (`web/llm/`) is abstracted. Today it uses Claude, but the interface supports swapping to GPT, DeepSeek, or others by adding one file.

4. **Tab isolation** -- Each browser tab has its own chat history and pinned items. They don't bleed into each other.

5. **Hybrid auto-detection** -- Skills activate automatically based on what you ask. Keywords handle common phrases instantly; an LLM classifier catches everything else.

---

## How to Add a New Skill

1. Create `web/skills/myskill/tools.py` with four exports:
   - `SKILL_ID = "myskill"`
   - `TOOL_DEFS = [...]` -- tool schemas the AI can call
   - `TOOL_HANDLERS = {"tool_name": function}` -- the actual Python functions
   - `TOOL_STATUS = {"tool_name": "Spinner text..."}` -- what the user sees while it runs

2. Create `web/skills/myskill/SKILL.md` -- instructions for the AI on when and how to use the skill

3. Restart the server. The skill is auto-discovered and available.

---

## Technology Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| AI | Claude (Anthropic) | Best tool-use and reasoning capability |
| Backend | Python + FastAPI | Fast async server, great for streaming |
| Frontend | Vanilla JS (no framework) | Simple, fast, no build step |
| M365 Integration | Microsoft Graph API | Official API for Outlook, Teams, Calendar, OneDrive |
| Slack Integration | Slack MCP Server | Official Slack tool protocol |
| Jira/Confluence | REST APIs | Atlassian's standard API |
| Streaming | Server-Sent Events (SSE) | Simple one-way streaming from server to browser |
