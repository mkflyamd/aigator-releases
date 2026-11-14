// Detects "out of usage" messages in a coding-agent terminal's output so the
// UI can offer a handoff. Runs in the browser on the chunks the terminal tab
// already receives; nothing is sent to a server.
(function (root) {
  'use strict';

  const TAIL_CHARS = 2048;
  const RESET_AFTER_CHARS = 4000;
  const SUPPRESS_AFTER_HANDOFF_MS = 60000;
  const ANSI =
    /\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)|\u001b\[[0-?]*[ -/]*[@-~]|\u001b[@-Z\\-_]/g;

  const GATEWAY = [
    /budget[_ ]?exceeded/i,
    /budget\s+has\s+been\s+exceeded/i,
    /exceeded\s+(?:your\s+|the\s+)?(?:current\s+)?budget/i,
    /ExceededBudget/,
    /insufficient[_ ]quota/i,
    /rate limit(?:ed)? exceeded/i,
    /\b429\b[^\n]{0,80}(?:too many requests|rate limit|quota)/i,
  ];
  const PATTERNS = {
    claude: [
      /usage limit reached/i,
      /(?:5-hour|weekly|session|opus)\s+limit\s+reached/i,
      /you(?:'|’)ve hit your (?:usage )?limit/i,
      /limit reached\s*[·∙•|-]\s*resets/i,
    ],
    codex: [/you(?:'|’)ve hit your usage limit/i, /usage limit[^\n]{0,80}try again/i],
    'opencode-bare': GATEWAY,
    crush: GATEWAY,
  };

  function stripAnsi(s) {
    return String(s).replace(ANSI, '').replace(/\r\n?/g, '\n');
  }

  function detect(agent, tail) {
    const patterns = PATTERNS[agent];
    if (!patterns) return false;
    const text = stripAnsi(tail);
    return patterns.some((p) => p.test(text));
  }

  function feed(sess, chunk, onLimit, now) {
    const t = now == null ? Date.now() : now;
    sess._limitTail = ((sess._limitTail || '') + stripAnsi(chunk)).slice(-TAIL_CHARS);
    const hit = detect(sess.agent, sess._limitTail);
    if (sess._limitOffered) {
      sess._limitSince = (sess._limitSince || 0) + String(chunk).length;
      if (!hit && sess._limitSince > RESET_AFTER_CHARS) {
        sess._limitOffered = false;
        sess._limitSince = 0;
      }
      return false;
    }
    if (!hit) return false;
    if (sess._handedOffAt && t - sess._handedOffAt < SUPPRESS_AFTER_HANDOFF_MS) return false;
    sess._limitOffered = true;
    sess._limitSince = 0;
    onLimit(sess);
    return true;
  }

  const api = { stripAnsi, detect, feed };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.agentLimitDetect = api;
})(typeof window !== 'undefined' ? window : globalThis);
