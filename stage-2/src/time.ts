// RFC 3339 instants for seeded expiry times, and expiry arithmetic (plan 3.7, D48).

const RFC3339_RE = /^(\d{4})-(\d\d)-(\d\d)[Tt](\d\d):(\d\d):(\d\d)(?:\.(\d+))?(?:([Zz])|([+-])(\d\d):(\d\d))$/;

// The latest instant a four-digit-year timestamp can name.
export const MAX_TS_MS = Date.UTC(9999, 11, 31, 23, 59, 59, 999);

function daysIn(year: number, month: number): number {
  if (month === 2) return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

// The instant an RFC 3339 date-time names, as whole milliseconds rounded up: an expiry at
// 12:00:00.0004 has not passed at 12:00:00.000 and has at 12:00:00.001, so comparing a
// millisecond clock with the rounded-up value is exact. null when the text is not a real
// RFC 3339 date-time (calendar date, hours 00-23, minutes and seconds 00-59).
export function rfc3339Ms(text: string): number | null {
  const m = RFC3339_RE.exec(text);
  if (!m) return null;
  const [year, month, day, hour, minute, second] = m.slice(1, 7).map(Number);
  if (month < 1 || month > 12 || day < 1 || day > daysIn(year, month)) return null;
  if (hour > 23 || minute > 59 || second > 59) return null;
  let offset = 0;
  if (m[9] !== undefined) {
    const offHours = Number(m[10]);
    const offMinutes = Number(m[11]);
    if (offHours > 23 || offMinutes > 59) return null;
    offset = (m[9] === '-' ? -1 : 1) * (offHours * 60 + offMinutes) * 60_000;
  }
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, second, 0);
  const fraction = m[7] ?? '';
  const millis = Number(fraction.slice(0, 3).padEnd(3, '0'));
  const beyond = /[1-9]/.test(fraction.slice(3)) ? 1 : 0;
  return date.getTime() - offset + millis + beyond;
}
