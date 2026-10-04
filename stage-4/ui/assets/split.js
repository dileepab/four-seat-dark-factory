// The split rule (stage-1 §9), the same as the server's `equalShares`: whole minor units that
// sum to the amount and differ by at most one, the larger shares going to the earliest handles.

export const MAX_PARTICIPANTS = 200;

export function equalShares(amount, n) {
  const base = Math.floor(amount / n);
  const remainder = amount - base * n;
  return Array.from({ length: n }, (_, i) => base + (i < remainder ? 1 : 0));
}

// One handle as people type it: trimmed, one leading `@` removed (D45).
export function cleanHandle(text) {
  const trimmed = String(text).trim();
  return trimmed.startsWith('@') ? trimmed.slice(1).trim() : trimmed;
}

// A comma-separated list of handles, in order. Empty entries are dropped; a repeated handle or
// more than 200 handles is an error. Returns { handles } or { error }.
export function parseHandles(text) {
  const handles = String(text).split(',').map(cleanHandle).filter((h) => h !== '');
  if (handles.length === 0) return { error: 'Enter at least one handle, separated by commas.' };
  if (handles.length > MAX_PARTICIPANTS) return { error: `A split takes at most ${MAX_PARTICIPANTS} people.` };
  const seen = new Set();
  for (const handle of handles) {
    if (seen.has(handle)) return { error: `@${handle} is listed twice.` };
    seen.add(handle);
  }
  return { handles };
}
