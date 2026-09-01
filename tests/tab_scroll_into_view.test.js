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

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');

const match = source.match(/function _tabScrollTargetLeft\([^)]*\)\s*\{[\s\S]*?\n\}/);
assert(match, '_tabScrollTargetLeft not found in app.js');
const _tabScrollTargetLeft = vm.runInNewContext(match[0] + '; _tabScrollTargetLeft;', {});

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

// --- Arrow-overlay-aware rightPad: close button must be fully visible -------
// When the right scroll arrow is visible (22px), the effective viewport is
// narrower. The rightPad passed to _tabScrollTargetLeft must include the arrow
// width so the target scroll position leaves room for the close button.
// Geometry: scroll at x=200, 300px wide. Tab at x=510, 80px wide (right=590).
// Without arrow awareness: target = (590-200)+80-300+8 = 78 → viewport 78..378,
// tab content 310..390 → right edge 390 is at viewport right (378)? No, 390>378.
// Wait, recompute: elLeft=510-200+0=310, elRight=390. clientWidth-rightPad=300-30=270.
// target = 390-270 = 120? No: elRight > scrollLeft+clientWidth → 390 > 0+270=270
// → yes. target = elRight - (clientWidth - rightPad) + pad = 390 - 270 + 8 = 128.
// After scroll: viewport 128..398, tab 310..390 fully visible with 8px pad to the
// right arrow.
const arrowPad = 30; // 22px arrow + 8px breathing room
const targetWithArrow = _tabScrollTargetLeft(
  scrollRect,
  0,
  300 - arrowPad,
  { left: 510, width: 80 },
  8,
);
assert(targetWithArrow > 0, 'with arrow-aware rightPad, a tab at the right edge must scroll');

// --- Guard: no blanket scroll-behavior:smooth on .tab-scroll ---------------
// The CSS rule caused programmatic scrollLeft restores to animate (visible
// glide + drift). Arrows now use scrollBy({behavior:'smooth'}) explicitly.
const cssSource = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'style.css'), 'utf8');
// Extract the .tab-scroll rule block
const tabScrollBlock = cssSource.match(/\.tab-scroll\s*\{[^}]+\}/);
assert(tabScrollBlock, '.tab-scroll CSS rule not found');
assert(
  !/scroll-behavior\s*:\s*smooth/.test(tabScrollBlock[0]),
  '.tab-scroll must NOT have scroll-behavior:smooth (programmatic restores must be instant)',
);

// --- Guard: arrow click handlers use scrollBy with smooth ------------------
assert(
  /scrollBy\(\s*\{\s*left:\s*-120,\s*behavior:\s*['"]smooth['"]\s*\}\s*\)/.test(source),
  'left arrow click must use scrollBy({left:-120,behavior:"smooth"})',
);
assert(
  /scrollBy\(\s*\{\s*left:\s*120,\s*behavior:\s*['"]smooth['"]\s*\}\s*\)/.test(source),
  'right arrow click must use scrollBy({left:120,behavior:"smooth"})',
);

// --- Guard: switchTab uses preserve-vs-reveal decision, not unconditional preserve
// The old code always set _preserveScrollOnRender=true, making the reveal path
// unreachable from normal tab clicks. The fix checks if the target tab is
// visible (accounting for arrow overlays) and sets _revealActiveTabOnRender=true
// when it's not.
assert(
  /_revealActiveTabOnRender\s*=\s*true/.test(source),
  'switchTab must set _revealActiveTabOnRender=true when the target tab is out of view',
);
// The visibility check must account for the arrow overlay width (22px).
assert(
  /_arrowW\s*=\s*22/.test(source),
  'switchTab visibility check must account for 22px sticky arrow overlays',
);

// --- Guard: _renderTabBar rAF uses arrow-aware visibility check ------------
// The activeTabOutOfView check must use effective left/right boundaries that
// subtract the arrow width, not the raw scrollRect edges.
assert(
  /effLeft/.test(source) && /effRight/.test(source),
  '_renderTabBar rAF must compute effective left/right boundaries for the arrow-aware visibility check',
);

console.log('tab_scroll_into_view: all assertions passed');
