// Request body parsing and JSON-value equality.

import { malformed } from './errors.ts';

export type JsonObject = { [key: string]: unknown };

export const MAX_DEPTH = 64;

const utf8 = new TextDecoder('utf-8', { fatal: true });

// Parse a request body that must be one JSON object (plan 3.2): valid UTF-8, valid JSON,
// not empty, nested at most `maxDepth` levels, no unpaired surrogates, an object at the top.
export function parseObject(raw: Buffer, maxDepth = MAX_DEPTH): JsonObject {
  let text: string;
  try {
    text = utf8.decode(raw);
  } catch {
    throw malformed('the request body is not valid UTF-8');
  }
  if (text.trim() === '') throw malformed('the request body is empty');
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw malformed('the request body is not valid JSON');
  }
  checkShape(value, maxDepth);
  if (!isObject(value)) throw malformed('the request body must be a JSON object');
  return value;
}

export function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function has(obj: JsonObject, key: string): boolean {
  return Object.hasOwn(obj, key);
}

// Depth and text checks, iterative so a hostile body cannot exhaust the stack.
function checkShape(root: unknown, maxDepth: number): void {
  const stack: Array<[unknown, number]> = [[root, 1]];
  while (stack.length > 0) {
    const [value, depth] = stack.pop()!;
    if (typeof value === 'string') {
      if (!value.isWellFormed()) throw malformed('the request body holds an unpaired surrogate');
    } else if (typeof value === 'object' && value !== null) {
      if (depth > maxDepth) throw malformed(`the request body is nested deeper than ${maxDepth} levels`);
      if (Array.isArray(value)) {
        for (const item of value) stack.push([item, depth + 1]);
      } else {
        for (const [key, item] of Object.entries(value)) {
          if (!key.isWellFormed()) throw malformed('the request body holds an unpaired surrogate');
          stack.push([item, depth + 1]);
        }
      }
    }
  }
}

// JSON-value equality: objects as key sets, arrays in order, numbers by value.
export function jsonEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (!jsonEqual(a[i], b[i])) return false;
    return true;
  }
  const ao = a as JsonObject;
  const bo = b as JsonObject;
  const keys = Object.keys(ao);
  if (keys.length !== Object.keys(bo).length) return false;
  for (const key of keys) {
    if (!Object.hasOwn(bo, key) || !jsonEqual(ao[key], bo[key])) return false;
  }
  return true;
}
