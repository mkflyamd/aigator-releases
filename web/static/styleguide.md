# AI Gator Style Guide

Design tokens, component patterns, and conventions for the AI Gator UI.

---

## 1. Design Tokens (CSS Variables)

### Colors

| Token | Value | Usage |
|-------|-------|-------|
| `--bg` | `#0a0f1a` | Page background |
| `--surface` | `#111827` | Primary surface (cards, panels) |
| `--surface2` | `#1a2332` | Hover states, nested containers |
| `--surface3` | `#1f2d40` | Layered/deep-nested components |
| `--border` | `#1e3a52` | Primary borders |
| `--border2` | `#2a4a6b` | Secondary borders, scrollbar thumbs |
| `--accent` | `#4ade80` | Primary CTA (green) |
| `--accent2` | `#22c55e` | Hover/pressed CTA |
| `--accent-glow` | `rgba(74,222,128,0.12)` | Accent glow overlay |
| `--text` | `#dbeafe` | Primary text |
| `--text-dim` | `#6b8db5` | Secondary text |
| `--text-sub` | `#4a6a8a` | Tertiary text, placeholders |
| `--user-bg` | `#0d3a5c` | User message bubble |
| `--danger` | `#ef4444` | Destructive actions |
| `--success` | `#22c55e` | Success state |
| `--warn` | `#f59e0b` | Warning state |

### Layout

| Token | Value |
|-------|-------|
| `--sidebar-w` | `280px` |
| `--rail-w` | `64px` |
| `--skill-panel-w` | `240px` |
| `--topbar-h` | `52px` |
| `--tab-bar-h` | `36px` |
| `--third-pane-w` | `680px` (responsive) |
| `--third-pane-list-w` | `260px` |

### Radii

| Token | Value | Usage |
|-------|-------|-------|
| `--radius` | `12px` | Cards, modals |
| `--radius-sm` | `8px` | Buttons, form inputs |

### Transitions

| Token | Value |
|-------|-------|
| `--transition` | `0.2s cubic-bezier(0.4,0,0.2,1)` |

---

## 2. Typography

**Font family:** `-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', system-ui, sans-serif`
**Code font:** `'SF Mono', 'Fira Code', 'Cascadia Code', monospace`
**Base size:** `14px` (body)

### Scale

| rem | ~px | Usage |
|-----|-----|-------|
| `.65rem` | 9 | Tiny badges, helper text |
| `.72rem` | 10 | Chips, secondary meta |
| `.75rem` | 10.5 | Small buttons |
| `.78rem` | 11 | Search inputs, subtitles |
| `.8rem` | 11.2 | Form labels, action buttons |
| `.82rem` | 11.5 | Body text, toolbar titles |
| `.85rem` | 12 | Section headers |
| `.9rem` | 12.6 | Form titles |
| `1rem` | 14 | Default |

### Weights

- `400` — body text
- `500` — subtitles, secondary
- `600` — labels, headers, buttons
- `700` — bold emphasis, avatars

---

## 3. Skill Accent Colors

Each integration has a unique color used in chips, badges, active states:

| Skill | Color | rgba(…, .1) bg | rgba(…, .3) border |
|-------|-------|----------------|---------------------|
| **Email/Outlook** | `#4a9ede` | `rgba(15,108,189,.12)` | `rgba(15,108,189,.35)` |
| **Teams** | `#64b5f6` | `rgba(100,181,246,.12)` | `rgba(100,181,246,.35)` |
| **Calendar** | `#00b4d8` | `rgba(0,180,216,.1)` | `rgba(0,180,216,.3)` |
| **OneDrive** | `#93c5fd` | `rgba(147,197,253,.1)` | `rgba(147,197,253,.3)` |
| **Jira** | `#fbbf24` | `rgba(245,158,11,.1)` | `rgba(245,158,11,.3)` |
| **Confluence** | `#a3e635` | `rgba(163,230,53,.1)` | `rgba(163,230,53,.3)` |
| **GitHub** | `#d1d5db` | `rgba(209,213,219,.1)` | `rgba(209,213,219,.3)` |
| **Slack** | `#e01e5a` | `rgba(224,30,90,.1)` | `rgba(224,30,90,.3)` |
| **ADO** | `#60a5fa` | `rgba(96,165,250,.1)` | `rgba(96,165,250,.3)` |

**Pattern for skill-specific highlights:**
```css
background: rgba(SKILL_COLOR, .1);    /* 10% for background */
border:     1px solid rgba(SKILL_COLOR, .3);  /* 30% for border */
color:      SKILL_COLOR;               /* Full for text */
```

---

## 4. Components

### Inputs & Text Fields

```css
background: rgba(255,255,255,.06);
border: 1px solid rgba(255,255,255,.11);
border-radius: 9px;                  /* forms: 9px, toolbar: 6px */
color: var(--text);
font-size: .78rem to .82rem;
padding: 9px 12px;                   /* forms */
padding: .25rem .5rem;               /* toolbar compact */
outline: none;
transition: border-color .18s, box-shadow .18s, background-color .18s;
```

**States:**
```css
:hover  { background: rgba(255,255,255,.09); border-color: rgba(255,255,255,.2); }
:focus  { border-color: var(--accent); }
::placeholder { color: var(--text-sub); }
```

### Select / Dropdown

**NEVER use native `<select>`.** Always build a custom dropdown. Native selects render with OS-level chrome (Windows 98 look) that ignores dark theme styling.

**Custom select structure** (see `.jira-csel-*` or `.cf-scope-csel-*` in CSS):
```
[trigger button]          ← styled like an input
  [label]                 ← current value text
  [chevron svg]           ← 10-12px, rotates 180deg when open
[panel]                   ← body-portalled, position: fixed, z-index: 9999
  [option]*               ← hover/selected states
```

**Trigger (full-size form):**
```css
background: rgba(255,255,255,.06);
border: 1px solid rgba(255,255,255,.11);
border-radius: 9px;
color: var(--text); font-size: 13px;
padding: 9px 12px;
transition: border-color .15s, background .15s, box-shadow .15s;
:hover  { background: rgba(255,255,255,.09); border-color: rgba(255,255,255,.2); }
.open   { border-color: rgba(SKILL_ACCENT,.5); box-shadow: 0 0 0 3px rgba(SKILL_ACCENT,.15); }
```

**Trigger (compact/toolbar):**
```css
padding: .25rem .45rem;
border-radius: 6px;
font-size: .78rem;
```

**Chevron:**
```css
color: rgba(255,255,255,.35);
transition: transform .18s ease;
.open { transform: rotate(180deg); }
```

**Floating panel:**
```css
position: fixed; z-index: 9999;
background: var(--surface);
border: 1px solid var(--border2);
border-radius: var(--radius-sm);             /* 8px */
box-shadow: 0 4px 16px rgba(0,0,0,.45);
overflow: hidden;                            /* CRITICAL — clips hover bg to panel edges */
/* NO padding on the panel — padding creates gaps where hover can't reach the edges.
   Let overflow:hidden + border-radius handle the clipping. */
/* Animate in */
opacity: 0; transform: translateY(-4px) scale(.97); pointer-events: none;
transition: opacity .14s ease, transform .14s ease;
.open { opacity: 1; transform: translateY(0) scale(1); pointer-events: auto; }
```

**Option:**
```css
padding: .4rem .8rem;
font-size: .8rem; color: var(--text);
cursor: pointer; white-space: nowrap;
transition: background var(--transition);
:hover    { background: var(--surface2); }
.selected { background: rgba(SKILL_ACCENT,.1); color: SKILL_ACCENT; font-weight: 500; }
```

> **Edge-fill rule:** The panel has `overflow: hidden` and zero padding.
> Option hover backgrounds fill edge-to-edge. The panel's `border-radius`
> clips the corners automatically. This matches `tp-ctx-menu` (Outlook
> right-click). Never add `padding` to the panel or `border-radius` to
> individual options — both cause visible gaps at the edges.

**Key rules:**
- Panel lives on `document.body` (escapes overflow clipping)
- Position with `getBoundingClientRect()` on trigger, flip above if no space below
- Close on outside click
- Clean up panel on destroy (remove from body, remove outside-click listener)

### Buttons

**Primary:**
```css
background: var(--accent); color: #000;
border: none; border-radius: var(--radius-sm);
font-size: .8rem; font-weight: 600;
padding: .45rem .9rem;
:hover { background: var(--accent2); color: #fff; }
:disabled { opacity: .4; cursor: not-allowed; }
```

**Ghost:**
```css
background: var(--surface2); color: var(--text-dim);
border: 1px solid var(--border); border-radius: var(--radius-sm);
:hover { border-color: var(--accent); color: var(--text); }
```

**Toolbar button:**
```css
width: 26px; height: 26px;
background: none; border: none; border-radius: 5px;
color: var(--text-dim);
:hover { background: var(--surface2); color: var(--text); }
```

### Chips / Pills

```css
display: inline-flex; align-items: center; gap: .3rem;
font-size: .72rem; font-weight: 600;
padding: .18rem .45rem; border-radius: 12px;
border: 1px solid var(--chip-border);
background: var(--chip-bg); color: var(--chip-color);
```

### Tabs

```css
.tab {
  background: none; border: none;
  color: var(--text-dim); font-size: 12px; font-weight: 500;
  padding: 8px 12px; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -1px;
  transition: color .15s, border-color .15s;
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--text); border-bottom-color: SKILL_ACCENT; }
```

### Cards

```css
background: var(--surface);
border: 1px solid var(--border);
border-radius: var(--radius);
overflow: hidden;
```

**Card header:** `padding: .6rem .9rem; background: var(--surface2); border-bottom: 1px solid var(--border);`
**Card item:** `padding: .6rem .9rem; border-bottom: 1px solid var(--border); :hover { background: var(--surface2); }`

### List rows

```css
display: flex; align-items: center; gap: 8px;
padding: 7px 14px; cursor: pointer;
border-bottom: 1px solid rgba(255,255,255,.04);
transition: background .12s;
:hover { background: rgba(255,255,255,.06); }
.active { background: rgba(SKILL_COLOR, .12); }
```

### Avatars

```css
width: 28px; height: 28px; border-radius: 50%;
background: var(--accent); color: #fff;
font-size: .72rem; font-weight: 700;
display: flex; align-items: center; justify-content: center;
```

### Scrollbars

Both vertical and horizontal scrollbars use the same styling. Always apply both axes.

```css
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 4px; }
scrollbar-width: thin;
scrollbar-color: var(--border2) transparent;
```

> **`height: 4px` is required** — without it, horizontal scrollbars render with
> the OS default (bright gray, full-height). Always pair `width` and `height`
> on `::-webkit-scrollbar`.

**Inside iframes:** CSS variables don't cross the iframe boundary, so use the
raw color value instead of `var(--border2)`:
```css
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(42,74,107,.8); border-radius: 4px; }
* { scrollbar-width: thin; scrollbar-color: rgba(42,74,107,.8) transparent; }
```

---

## 5. Surface Hierarchy

```
--bg       (#0a0f1a)   Base background
  --surface  (#111827)   Panels, cards
    --surface2 (#1a2332)   Hover, nested
      --surface3 (#1f2d40)   Deep nesting
```

**Text hierarchy:** `--text` > `--text-dim` > `--text-sub`
**Border hierarchy:** `--border` (subtle) > `--border2` (visible)
**Disabled:** `opacity: .4 to .5; cursor: not-allowed`

---

## 6. Interactive States

| State | Pattern |
|-------|---------|
| Default | `background: var(--surface)` |
| Hover | `background: var(--surface2)` |
| Focus | `border-color: var(--accent)` |
| Active | `background: rgba(ACCENT, .1)` |
| Disabled | `opacity: .4; cursor: not-allowed` |

---

## 7. Spacing Conventions

- Toolbar compact: `.25rem .5rem` padding
- Form fields: `9px 12px` padding
- Cards/sections: `.6rem .9rem` padding
- List items: `7px 14px` padding
- Flex gaps: `.3rem` (tight) / `.5rem` (standard) / `.75rem` (spacious)
- Section headers: `font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: rgba(255,255,255,.35); padding: 8px 14px 4px`

---

## 8. Animation Timing

- Fast micro-interactions: `0.12s - 0.15s`
- Standard transitions: `0.18s - 0.2s` with `cubic-bezier(0.4,0,0.2,1)`
- Pane open/close: `0.5s`
- Skeleton shimmer: `1.4s ease-in-out infinite`
- Spin: `0.8s linear infinite`
- Gator swim: `1.2s ease-in-out infinite`
- Gator dot fade: `1.2s ease-in-out infinite` (staggered 0s / .2s / .4s)

---

## 9. Gator Loading Animation

Used across all third-pane loading states (Teams thread, email detail, list loading, pane switching).

**Structure:**
```html
<div class="gator-loading">
  <div class="gator-loading-icon">
    <span class="gator-chomp">🐊</span>
    <span class="gator-dots"><span>.</span><span>.</span><span>.</span></span>
  </div>
  <div class="gator-loading-tip">Chomping through data…</div>
</div>
```

**CSS:**
```css
.gator-loading {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: .6rem;
  padding: 2rem; min-height: 120px;
}
.gator-loading-icon { display: flex; align-items: center; gap: .1rem; font-size: 1.6rem; }
.gator-chomp { animation: gator-swim 1.2s ease-in-out infinite; }
@keyframes gator-swim {
  0%, 100% { transform: translateX(0); }
  50% { transform: translateX(8px); }
}
.gator-dots span { opacity: 0; animation: gator-dot-fade 1.2s ease-in-out infinite; }
.gator-dots span:nth-child(1) { animation-delay: 0s; }
.gator-dots span:nth-child(2) { animation-delay: .2s; }
.gator-dots span:nth-child(3) { animation-delay: .4s; }
.gator-loading-tip { font-size: .76rem; color: var(--text-sub); font-style: italic; }
```

**Loading tips** (randomized each render):
- *Wading through the swamp…*
- *Chomping through data…*
- *Swimming upstream…*
- *Snapping up messages…*
- *Surfacing shortly…*
- *Tail-whipping the API…*
- *Lurking in the data lake…*
- *Crunching bytes…*

**Usage (JS):**
```javascript
col.innerHTML = _gatorLoading();
```

---

## 10. Right-Click Context Menu

Used for item actions in Teams, Email, OneDrive (mark read/unread, pin, delete, etc.).

**Structure:**
```html
<div class="tp-ctx-menu" style="position:fixed; left:Xpx; top:Ypx">
  <button class="tp-ctx-item">
    <span class="tp-ctx-item-icon">✔️</span> Mark as read
  </button>
  <button class="tp-ctx-item">
    <span class="tp-ctx-item-icon">📌</span> Pin to Chat
  </button>
</div>
```

**CSS:**
```css
.tp-ctx-menu {
  position: fixed;
  display: flex; flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--border2);
  border-radius: var(--radius-sm);       /* 8px */
  box-shadow: 0 4px 16px rgba(0,0,0,.45);
  padding: 0;                            /* ZERO — edge-fill rule */
  z-index: 999;
  min-width: 180px;
  overflow: hidden;                      /* clips hover bg to rounded corners */
}
.tp-ctx-item {
  display: flex; align-items: center; gap: .5rem;
  padding: .4rem .8rem;
  font-size: .8rem; color: var(--text);
  cursor: pointer;
  background: none; border: none; text-align: left;
  font-family: inherit;
  transition: background var(--transition);
  white-space: nowrap;
}
.tp-ctx-item:hover { background: var(--surface2); }
.tp-ctx-item-icon { font-size: .85rem; width: 1rem; text-align: center; }
```

**Key rules:**
- Position with `e.clientX / e.clientY` from the contextmenu event
- Flip direction if menu would overflow viewport
- Close on outside click or Escape
- `overflow: hidden` on menu + zero padding = hover fills edge-to-edge (same rule as dropdowns)
