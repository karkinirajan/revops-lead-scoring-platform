/*
 * Checks that jsdom cannot make, to run in a real browser against the running app (a production build: `npm run build && npm start`).
 * Sign in, open a page, paste this whole file into the DevTools console, then call:
 *
 *   await audit()                 // contrast and horizontal overflow of the current page
 *   await audit({ focus: 25 })    // also press Tab 25 times and report any focused element with no visible focus indicator
 *
 * Resize the window to 1280, 768 and 390 pixels wide and run it at each. It prints a table and returns the findings; an empty `failures` list is a pass.
 * Contrast is WCAG AA: 4.5:1 for text, 3:1 for text of 24px or more (or 18.66px and bold). Text over a gradient or an image is not handled.
 */
async function audit({ focus = 0 } = {}) {
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const linear = (v) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  const luminance = ({ r, g, b }) => 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const background = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c.a > 0) {
        layers.push(c);
        if (c.a === 1) break;
      }
    }
    let bg = parse(getComputedStyle(document.body).backgroundColor) ?? { r: 0, g: 0, b: 0, a: 1 };
    if (layers.length && layers[layers.length - 1].a === 1) bg = layers.pop();
    while (layers.length) bg = over(layers.pop(), bg);
    return bg;
  };

  const failures = { contrast: [], overflow: [], focus: [] };
  const seen = new Map();
  let textNodes = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.textContent.trim()) continue;
    const el = node.parentElement;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || el.closest('script,style')) continue;
    textNodes++;
    const bg = background(el);
    const [hi, lo] = [luminance(over(parse(style.color), bg)), luminance(bg)].sort((a, b) => b - a);
    const ratio = (hi + 0.05) / (lo + 0.05);
    const size = parseFloat(style.fontSize);
    const large = size >= 24 || (size >= 18.66 && parseInt(style.fontWeight, 10) >= 700);
    const needed = large ? 3 : 4.5;
    if (ratio < needed) {
      const key = `${style.color} on rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)}) at ${style.fontSize}`;
      const entry = seen.get(key) ?? { colours: key, ratio: +ratio.toFixed(2), needed, count: 0, example: node.textContent.trim().slice(0, 30) };
      entry.count++;
      seen.set(key, entry);
    }
  }
  failures.contrast = [...seen.values()];

  const viewport = document.documentElement.clientWidth;
  const inScroller = (el) => {
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      const x = getComputedStyle(e).overflowX;
      if (x === 'auto' || x === 'scroll') return true;
    }
    return false;
  };
  for (const el of document.querySelectorAll('main *')) {
    const box = el.getBoundingClientRect();
    if (box.width && box.right > viewport + 1 && !inScroller(el)) failures.overflow.push(`${el.tagName.toLowerCase()} reaches ${Math.round(box.right)}px of ${viewport}px: "${(el.textContent || '').trim().slice(0, 30)}"`);
  }
  if (document.documentElement.scrollWidth > viewport) failures.overflow.push(`the page itself scrolls sideways (${document.documentElement.scrollWidth}px of ${viewport}px)`);

  if (focus) {
    document.activeElement?.blur();
    for (let i = 0; i < focus; i++) {
      // the console cannot press Tab for you: move focus the way Tab would, to the next focusable element, and ask the browser if it matches :focus-visible
      const focusable = [...document.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])')].filter((e) => e.getClientRects().length);
      const next = focusable[(focusable.indexOf(document.activeElement) + 1) % focusable.length];
      next.focus({ focusVisible: true });
      const style = getComputedStyle(next);
      const outline = style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0;
      const ring = style.boxShadow !== 'none';
      if (!outline && !ring) failures.focus.push(`${next.tagName.toLowerCase()} "${(next.getAttribute('aria-label') || next.textContent || '').trim().slice(0, 30)}"`);
    }
  }

  console.table(failures.contrast);
  console.log(`${textNodes} text nodes checked; ${failures.contrast.length} contrast groups, ${failures.overflow.length} overflows, ${failures.focus.length} elements without a focus indicator`);
  return failures;
}
