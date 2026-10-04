// Money in the browser (plan 3.14, I39, I40, D44): exact formatting of integer minor units,
// and the amount grammar, parsed without floating point.

export const MAX_AMOUNT = 1_000_000_000;

// `100.00 EUR`; with minor_units 0 there is no decimal point (`1200 JPY`). No grouping, no sign.
export function formatMoney(minor, minorUnits, currency) {
  if (minorUnits === 0) return `${minor} ${currency}`;
  const digits = String(minor).padStart(minorUnits + 1, '0');
  return `${digits.slice(0, -minorUnits)}.${digits.slice(-minorUnits)} ${currency}`;
}

// The decimal form of an amount as typed into an amount field: `20.00`, or `2000` for JPY.
export function decimalText(minor, minorUnits) {
  return formatMoney(minor, minorUnits, '').trimEnd();
}

// Trimmed text matching ^[0-9]+(\.[0-9]{1,m})?$ (no `.` at all when m is 0), worth 1 to
// 1000000000 minor units. Returns { value } or { error } with a message for people.
export function parseAmount(text, minorUnits) {
  const trimmed = String(text).trim();
  if (trimmed === '') return { error: 'Enter an amount.' };
  const pattern = minorUnits === 0 ? /^([0-9]+)$/ : new RegExp(`^([0-9]+)(?:\\.([0-9]{1,${minorUnits}}))?$`);
  const match = pattern.exec(trimmed);
  if (!match) {
    if (/^[0-9]+\.[0-9]+$/.test(trimmed)) {
      return { error: minorUnits === 0
        ? 'This currency has no decimal places: enter a whole amount.'
        : `Use at most ${minorUnits} decimal places.` };
    }
    return { error: minorUnits === 0
      ? 'Enter a whole amount, such as 15.'
      : 'Enter an amount such as 15 or 15.50, using only digits and a decimal point.' };
  }
  const fraction = (match[2] ?? '').padEnd(minorUnits, '0');
  const value = BigInt(match[1]) * 10n ** BigInt(minorUnits) + BigInt(fraction || '0');
  if (value < 1n) return { error: 'The amount must be more than zero.' };
  if (value > BigInt(MAX_AMOUNT)) return { error: `The amount can be at most ${formatMoney(MAX_AMOUNT, minorUnits, '').trim()}.` };
  return { value: Number(value) };
}
