## Purpose
Browse the web, search for information, visit websites, fill forms, and extract data from web pages.

## When to use
- **browser_search**: User asks to search the web generally ("search for X", "google Y", "find info about Z"). Uses Google.
- **browser_navigate**: User mentions a specific URL or website ("go to priceline.com", "open reddit", "check this link"). Navigates directly.
- **browser_task**: User wants a complex multi-step interaction ("book a flight on Priceline", "fill out the form at [URL]", "compare prices on 3 sites", "find the cheapest option on [site]"). The agent plans and executes steps autonomously.

## Instructions
- If the user mentions a specific website, use browser_task or browser_navigate — do NOT search Google for it.
- For browser_task, be detailed in the task description. Include: which site, what to search/fill, what data to extract, what format to return.
- The browser opens visibly so the user can see what's happening.
- If the task requires login, the browser will pause for the user to take over.
- After the task, summarize the findings concisely.
- **CRITICAL: Only call ONE browser tool per response.** The browser can only run one task at a time.
- **If the current message contains multiple browser requests**, do NOT silently pick one and do NOT call any tools yet. Respond by briefly listing the tasks you identified and ask the user which one to start with. Keep it short — one line per task, numbered.
- **NEVER say the request is a duplicate.** Every new user message is a fresh request — always run the browser tool. Do NOT look at conversation history to decide whether to skip a task.

## Examples
- "Search the web for latest AI news" → browser_search(query="latest AI news")
- "Go to reddit.com and show me trending posts" → browser_navigate(url="https://www.reddit.com", extract_content="top trending posts")
- "Find the cheapest flight to NYC tomorrow on Priceline" → browser_task(task="Go to priceline.com, search for flights to New York City departing tomorrow, find the cheapest options, and return airline, price, departure time, and duration for the top 5 cheapest flights", start_url="https://www.priceline.com/flights")
- "Compare hotel prices for Paris on Booking.com and Expedia" → browser_task(task="Visit booking.com and expedia.com, search for hotels in Paris for [dates], extract the top 5 cheapest options from each site, and compare them side by side")
