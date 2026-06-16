// Issue #81: A newly created tab is scrolled partially off the right edge and
// renders "too narrow" (label truncated to "Ne…" with a "›" overflow arrow).
//
// Root cause: the old scroll-into-view math used activeEl.offsetLeft, which is
// measured from the nearest *positioned* ancestor (.topbar is position:fixed),
// NOT from the .tab-scroll container. Comparing that against scroll.scrollLeft /
// clientWidth mixes coordinate systems, so the active tab is never revealed.
//
// The fix extracts a pure helper _tabScrollTargetLeft that works purely in the
// scroll container's own coordinate space (derived from getBoundingClientRect),
// so it is correct regardless of which ancestor is the offsetParent.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'app.js'),
  'utf8',
);

const match = source.match(
  /function _tabScrollTargetLeft\([^)]*\)\s*\{[\s\S]*?\n\}/,
);
assert(match, '_tabScrollTargetLeft not found in app.js');
const _tabScrollTargetLeft = vm.runInNewContext(
  match[0] + '; _tabScrollTargetLeft;',
  {},
);

// Geometry: scroll container starts at viewport x=200 (logo + arrows to its
// left) and is 300px wide. A freshly appended tab sits at viewport x=480, 80px
// wide, so its right edge (560) is past the container's right edge (500) — it is
// partially off-screen. The helper must scroll so the tab is fully revealed.
const scrollRect = { left: 200 };
const elRect = { left: 480, width: 80 };
const target = _tabScrollTargetLeft(scrollRect, 0, 300, elRect, 8);

// Content-space: elLeft = 480-200+0 = 280, elRight = 360. To fit within a 300px
// viewport we scroll to 360-300+8 = 68. After scrolling, viewport spans 68..368,
// fully containing the tab (280..360) with the 8px pad.
assert.strictEqual(target, 68, 'must scroll right to fully reveal a new tab');

// Already-visible tab: no scroll change.
const visibleEl = { left: 260, width: 80 }; // content 60..140, inside 0..300
assert.strictEqual(
  _tabScrollTargetLeft(scrollRect, 0, 300, visibleEl, 8),
  0,
  'a fully-visible tab must not move the scroll position',
);

// Left-overflow: a tab scrolled off the left edge is revealed, clamped at >=0.
// elLeft = 150-200+200 = 150 < scrollLeft(200) -> reveal: max(0, 150-8) = 142.
const leftTarget = _tabScrollTargetLeft(scrollRect, 200, 300, { left: 150, width: 80 }, 8);
assert.strictEqual(leftTarget, 142, 'a tab off the left edge scrolls left to reveal it');

// Never returns a negative scroll position.
const clamped = _tabScrollTargetLeft(scrollRect, 5, 300, { left: 198, width: 80 }, 8);
assert(clamped >= 0, 'scroll position must never be negative');

console.log('tab_scroll_into_view: all assertions passed');
