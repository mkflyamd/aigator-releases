/**
 * gatorEmptyState(hints)
 *
 * Reusable empty-state component — CSS 3D gator head that peeks up
 * from the bottom of a panel, with contextual action hints.
 *
 * Usage:
 *   col.innerHTML = gatorEmptyState([
 *     { icon: '✉', text: 'Select an email to read it' },
 *     { icon: '✏', text: 'Or compose a new one'       },
 *   ]);
 *
 * The peek animation triggers automatically on mount via the
 * .gator-empty-peek-trigger class — no extra JS needed.
 */
function gatorEmptyState(hints = []) {
  const hintRows = hints.map(h => {
    // If icon starts with '<' treat as raw HTML (inline SVG / img), otherwise plain text/emoji
    const iconContent = h.icon.trimStart().startsWith('<')
      ? `<span class="ge-hint-icon ge-hint-icon-svg">${h.icon}</span>`
      : `<span class="ge-hint-icon">${h.icon}</span>`;
    return `<div class="ge-hint">${iconContent}<span>${h.text}</span></div>`;
  }).join('');

  return `
<div class="gator-empty">
  <div class="gator-empty-stage">
    <div class="gator-empty-head gator-empty-peek-trigger">
      <div class="ge-highlight"></div>
      <div class="ge-snout">
        <div class="ge-nostril ge-nostril-l"></div>
        <div class="ge-nostril ge-nostril-r"></div>
      </div>
      <div class="ge-eye ge-eye-l">
        <div class="ge-iris"><div class="ge-pupil"></div><div class="ge-catchlight"></div></div>
      </div>
      <div class="ge-eye ge-eye-r">
        <div class="ge-iris"><div class="ge-pupil"></div><div class="ge-catchlight"></div></div>
      </div>
      <div class="ge-brow ge-brow-l"></div>
      <div class="ge-brow ge-brow-r"></div>
    </div>
    <div class="ge-ledge"></div>
  </div>
  <div class="ge-hints">${hintRows}</div>
</div>`;
}
