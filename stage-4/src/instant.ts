// Instants (plan 3.4, D66): the RFC 3339 grammar the API accepts, and an exact comparison key.
//
// An instant's key is its whole seconds since the epoch, shifted to be positive and padded to
// a fixed width, then '.', then its fraction digits without trailing zeros. Plain string order
// of keys is time order at every digit given, and two texts naming the same instant
// (`...Z`, `...+00:00`, `.5` and `.500`) have the same key. Nothing is rounded.

const INSTANT_RE = /^([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?(?:([Zz])|([+-])([0-9]{2}):([0-9]{2}))$/;

export const MAX_INSTANT_LENGTH = 64;

// Year 0000 at offset +23:59 is about -6.2e10 s and year 9999 about 2.5e11 s: adding 1e12 keeps
// every key's seconds positive and 13 digits wide.
const SHIFT = 1_000_000_000_000;

function daysIn(year: number, month: number): number {
  if (month === 2) return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

function key(seconds: number, fraction: string): string {
  return `${String(seconds + SHIFT).padStart(13, '0')}.${fraction.replace(/0+$/, '')}`;
}

// The key of a client-supplied instant, or null when the text is not one: at most 64
// characters, a real calendar date, hours 00-23, minutes and seconds 00-59 (no leap second),
// offset hours 00-23 and minutes 00-59.
export function instantKey(text: unknown): string | null {
  if (typeof text !== 'string' || text.length > MAX_INSTANT_LENGTH) return null;
  const m = INSTANT_RE.exec(text);
  if (!m) return null;
  const [year, month, day, hour, minute, second] = m.slice(1, 7).map(Number);
  if (month < 1 || month > 12 || day < 1 || day > daysIn(year, month)) return null;
  if (hour > 23 || minute > 59 || second > 59) return null;
  let offset = 0;
  if (m[9] !== undefined) {
    const offHours = Number(m[10]);
    const offMinutes = Number(m[11]);
    if (offHours > 23 || offMinutes > 59) return null;
    offset = (m[9] === '-' ? -1 : 1) * (offHours * 60 + offMinutes) * 60;
  }
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day); // years 0-99 too, unlike Date.UTC
  date.setUTCHours(hour, minute, second, 0);
  return key(date.getTime() / 1000 - offset, m[7] ?? '');
}

// The key of a time the service issued, in whole milliseconds since the epoch.
export function msKey(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return key(seconds, String(ms - seconds * 1000).padStart(3, '0'));
}

// The key of a timestamp the service itself formatted (`formatTs`), or stored from an earlier
// stage: any valid instant text.
export function tsKey(text: string): string {
  const k = instantKey(text);
  if (k === null) throw new Error(`not an instant: ${text}`);
  return k;
}
