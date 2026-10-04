// The browser UI (plan 3.14, D39, D40, D59): one HTML shell for every UI route, and the static
// files under /assets/, all read once at start-up from stage-2/ui/. The UI routes are public:
// they never read Authorization; the page itself calls the JSON API with its bearer token.

import { readdirSync, readFileSync } from 'node:fs';
import type { Result } from './context.ts';

const UI_DIR = new URL('../ui/', import.meta.url);

export const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
  + "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
  + "frame-ancestors 'none'";

const HTML_HEADERS = {
  'Content-Type': 'text/html; charset=utf-8',
  'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Content-Security-Policy': CSP,
};

const TYPES: Record<string, string> = {
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
};

const shell = readFileSync(new URL('index.html', UI_DIR));
const assets = new Map<string, { type: string; body: Buffer }>();
for (const name of readdirSync(new URL('assets/', UI_DIR))) {
  const type = TYPES[name.slice(name.lastIndexOf('.'))];
  if (type) assets.set(`/assets/${name}`, { type, body: readFileSync(new URL(`assets/${name}`, UI_DIR)) });
}

// Paths that always answer the shell, and the two the JSON API shares (shell only for HTML).
const PAGES = new Set(['/', '/split', '/signup', '/login']);
const SHARED = new Set(['/requests', '/authorizations']);

// `Accept` lists text/html when one of its media ranges, parameters removed, trimmed and
// lower-cased, is exactly text/html and its q is not 0 (plan 3.2). */* does not count.
export function acceptsHtml(accept: string | string[] | undefined): boolean {
  const value = Array.isArray(accept) ? accept.join(',') : accept;
  if (!value) return false;
  return value.split(',').some((range) => {
    const [type, ...params] = range.split(';');
    if (type.trim().toLowerCase() !== 'text/html') return false;
    const q = params.map((p) => p.trim()).find((p) => /^q\s*=/i.test(p));
    return q === undefined || Number(q.slice(q.indexOf('=') + 1).trim()) !== 0;
  });
}

function page(status: number): Result {
  return { status, raw: { headers: HTML_HEADERS, body: shell } };
}

// The UI's answer to a GET of `path`, or null when the JSON API (or its 404) answers instead.
export function uiResponse(path: string, accept: string | string[] | undefined): Result | null {
  if (PAGES.has(path) || (SHARED.has(path) && acceptsHtml(accept))) return page(200);
  const asset = assets.get(path);
  if (asset) {
    return {
      status: 200,
      raw: { headers: { 'Content-Type': asset.type, 'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff' }, body: asset.body },
    };
  }
  return null;
}

// An unknown path asked for as a page: the shell shows its not-found screen (D59).
export function notFoundPage(accept: string | string[] | undefined): Result | null {
  return acceptsHtml(accept) ? page(404) : null;
}
