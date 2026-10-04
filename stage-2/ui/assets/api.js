// The page's calls to the JSON API (plan 3.14, D41, D43, D65).
//
// Every call sends `Accept: application/json`, and the bearer token when signed in. It ends
// in one of three outcomes:
//   ok       a 2xx whose body is a JSON object (201, or a 200 replay)
//   refused  a 4xx with the error envelope: the service said no, nothing happened
//   unknown  anything else: network failure, abort, no answer within 4 s, a 5xx, a 4xx
//            without the envelope, or a body that is not a JSON object (empty included).
//            The write may or may not have happened.

export const TIMEOUT_MS = 4000;
const TOKEN_KEY = 'pocketful.token';
const USER_KEY = 'pocketful.user';

function store() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export const session = {
  get token() {
    return store()?.getItem(TOKEN_KEY) ?? null;
  },
  // The last known signed-in user, so the header can show at once on every page load.
  get user() {
    try {
      return JSON.parse(store()?.getItem(USER_KEY) ?? 'null');
    } catch {
      return null;
    }
  },
  start(token) {
    store()?.setItem(TOKEN_KEY, token);
    store()?.removeItem(USER_KEY);
  },
  remember(me) {
    const { user_id: id, handle, display_name: name } = me;
    store()?.setItem(USER_KEY, JSON.stringify({ user_id: id, handle, display_name: name }));
  },
  end() {
    store()?.removeItem(TOKEN_KEY);
    store()?.removeItem(USER_KEY);
  },
};

let onSessionEnded = () => {};
export function whenSessionEnds(handler) {
  onSessionEnded = handler;
}

export async function call(method, path, { body, key, auth = true } = {}) {
  const headers = { Accept: 'application/json' };
  const token = auth ? session.token : null;
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response;
  let text;
  try {
    response = await fetch(path, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal, cache: 'no-store', credentials: 'omit',
    });
    text = await response.text();
  } catch {
    return { kind: 'unknown', reason: controller.signal.aborted ? 'timeout' : 'network' };
  } finally {
    clearTimeout(timer);
  }
  let data;
  try {
    data = text === '' ? null : JSON.parse(text);
  } catch {
    return { kind: 'unknown', reason: 'unreadable' };
  }
  const status = response.status;
  // Every answer the page uses is a JSON object: a 2xx with an empty body, or with any other
  // JSON, cannot be read as the result, so it is an unknown outcome too (3.14 Outcomes).
  if (status >= 200 && status < 300) {
    return isObject(data) ? { kind: 'ok', status, data } : { kind: 'unknown', reason: 'unreadable' };
  }
  const error = isObject(data) ? data.error : null;
  if (status >= 400 && status < 500 && error && typeof error.code === 'string') {
    // A 401 to a call that sent the token: the session is over (D65). Sign-in forms are not.
    if (status === 401 && token) onSessionEnded(token);
    return { kind: 'refused', status, code: error.code, message: describe(error.code, error.message) };
  }
  return { kind: 'unknown', reason: `status ${status}` };
}

function isObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

// Reads a whole list: the bare path first, then `offset`/`limit=200` pages while `has_more`,
// keeping each item once (D64).
export async function readAll(path, field, idOf) {
  const first = await call('GET', path);
  if (first.kind !== 'ok') return first;
  const items = [];
  const seen = new Set();
  // A page whose list is missing or not an array cannot be read: the load is unknown.
  const unreadable = (page) => !Array.isArray(page[field]);
  const take = (page) => {
    for (const item of page[field]) {
      const id = idOf(item);
      if (!seen.has(id)) {
        seen.add(id);
        items.push(item);
      }
    }
  };
  if (unreadable(first.data)) return { kind: 'unknown', reason: 'unreadable' };
  take(first.data);
  let more = first.data.has_more === true;
  let offset = first.data[field].length;
  while (more) {
    const next = await call('GET', `${path}?offset=${offset}&limit=200`);
    if (next.kind !== 'ok') return next;
    if (unreadable(next.data)) return { kind: 'unknown', reason: 'unreadable' };
    take(next.data);
    const count = next.data[field].length;
    offset += count;
    more = next.data.has_more === true && count > 0;
  }
  return { kind: 'ok', status: 200, data: items };
}

const MESSAGES = {
  insufficient_funds: 'Not enough available funds. Money on hold cannot be spent.',
  not_found: 'No one has that handle.',
  self_payment: 'You cannot send money to yourself.',
  self_request: 'You cannot request money from yourself.',
  request_not_pending: 'This request is no longer pending.',
  authorization_not_open: 'This hold is no longer open.',
  authorization_expired: 'This hold has expired.',
  capture_exceeds_authorization: 'That is more than the amount still on hold.',
  email_taken: 'An account with that email already exists.',
  forbidden: 'You are not allowed to do that.',
};

// A sentence for people: the known codes in plain words, otherwise the service's own message.
function describe(code, message) {
  if (MESSAGES[code]) return MESSAGES[code];
  const text = typeof message === 'string' && message ? message : 'The request was refused.';
  return text.charAt(0).toUpperCase() + text.slice(1).replace(/([^.!?])$/, '$1.');
}
