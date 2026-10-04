// Building the page from data. Text always goes in as text (textContent), never as HTML (I48).

const SVG_NS = 'http://www.w3.org/2000/svg';

// h('button', { type: 'button', class: 'x', testid: 'pay-submit', onclick: fn }, 'Pay')
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (name === 'testid') el.setAttribute('data-testid', value);
    else if (name === 'class') el.className = value;
    else if (name.startsWith('on')) el.addEventListener(name.slice(2), value);
    else if (name === 'value') el.value = value;
    else if (value === true) el.setAttribute(name, '');
    else el.setAttribute(name, String(value));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const PATHS = {
  wallet: ['M3 7h15a3 3 0 0 1 3 3v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z', 'M3 7l12-4 2 4', 'M16.5 14h.01'],
  requests: ['M4 6h16', 'M4 12h10', 'M4 18h7', 'M17 15l3 3-3 3'],
  split: ['M12 3v7', 'M12 10l-6 7', 'M12 10l6 7', 'M6 17v4', 'M18 17v4'],
  hold: ['M6 11V8a6 6 0 0 1 12 0v3', 'M5 11h14v10H5z'],
  lock: ['M7 11V8a5 5 0 0 1 10 0v3', 'M5 11h14v9H5z'],
  refresh: ['M20 11a8 8 0 1 0-2.3 5.7', 'M20 4v7h-7'],
  check: ['M5 12l5 5 9-10'],
  alert: ['M12 3l9 17H3z', 'M12 10v4', 'M12 17h.01'],
  clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 7v5l3 2'],
  out: ['M14 4h5v16h-5', 'M10 12h10', 'M7 9l-3 3 3 3'],
  arrow: ['M5 12h14', 'M13 6l6 6-6 6'],
};

// An inline SVG icon, decorative: hidden from assistive technology.
export function icon(name, cls = 'icon') {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', cls);
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  for (const d of PATHS[name] ?? []) {
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}

// Replace an element's children.
export function fill(el, ...children) {
  el.replaceChildren();
  return append(el, children);
}
