// Field rules shared by several endpoints. "Characters" are Unicode code points (D11).

export const HANDLE_RE = /^[a-z0-9_]{1,20}$/;

export function cpLength(s: string): number {
  let n = 0;
  for (const _ of s) n++;
  return n;
}

// Exactly one '@', a non-empty local part and domain, no whitespace or control
// characters, at most 254 code points (D12).
export function isEmail(email: string): boolean {
  if (cpLength(email) > 254) return false;
  const at = email.indexOf('@');
  if (at <= 0 || at !== email.lastIndexOf('@') || at === email.length - 1) return false;
  return !/[\s\p{Cc}]/u.test(email);
}

export function emailKey(email: string): string {
  return email.toLowerCase();
}

// Spec §4: the local part, lower-cased, every code point outside [a-z0-9_] replaced
// by '_', truncated to 20 code points.
export function deriveHandle(email: string): string {
  const local = email.slice(0, email.indexOf('@')).toLowerCase();
  let handle = '';
  let n = 0;
  for (const ch of local) {
    handle += /^[a-z0-9_]$/.test(ch) ? ch : '_';
    if (++n === 20) break;
  }
  return handle;
}
