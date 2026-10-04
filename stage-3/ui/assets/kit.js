// Pieces every signed-in screen shares: data loads where the latest wins, the money forms'
// write behaviour, status messages, the wallet summary and times for people.

import { call } from './api.js';
import { fill, h, icon } from './dom.js';
import { formatMoney } from './money.js';
import { RetryIdentity } from './retry.js';

// ---- loads ------------------------------------------------------------------------------

// A screen's data: each resource numbers its loads in the order they start, and a response
// or a failure is applied only when no later load of it has been applied (I44). `loading`
// shows until every resource's first load has settled; `load-error` and `load-retry` show
// while any resource's latest applied load failed.
export function createLoads(screen, region) {
  const resources = new Map();
  const failed = new Set();
  let firstPending = 0;
  const loading = h('p', { testid: 'loading', class: 'loading', role: 'status' },
    h('span', { class: 'spinner', 'aria-hidden': 'true' }), 'Loading…');

  function renderStatus() {
    keepFocus(renderStatusNow);
  }

  function renderStatusNow() {
    const children = [];
    if (firstPending > 0) children.push(loading);
    if (failed.size > 0) {
      children.push(h('div', { testid: 'load-error', class: 'message refused', role: 'alert' },
        icon('alert'),
        h('span', {}, 'We could not load the latest data. Check your connection and try again.'),
        h('button', { type: 'button', testid: 'load-retry', class: 'button secondary small', onclick: () => api.reloadAll() },
          'Try again')));
    }
    fill(region, children);
  }

  const api = {
    // `fetch` returns an outcome (api.js); `apply` renders the data of an ok outcome.
    add(name, fetch, apply) {
      resources.set(name, { fetch, apply, started: 0, applied: 0, settledFirst: false });
      return () => api.load(name);
    },
    async load(name) {
      const r = resources.get(name);
      const n = ++r.started;
      if (n === 1) {
        firstPending++;
        renderStatus();
      }
      const outcome = await r.fetch();
      if (!screen.alive) return outcome;
      if (n > r.applied) {
        r.applied = n;
        // The first answer applied, from whichever load, ends the screen's loading state.
        if (!r.settledFirst) {
          r.settledFirst = true;
          firstPending--;
        }
        if (outcome.kind === 'ok') {
          failed.delete(name);
          r.apply(outcome.data);
        } else if (!(outcome.kind === 'refused' && outcome.status === 401)) {
          failed.add(name);
        }
      }
      renderStatus();
      return outcome;
    },
    loadAll(...names) {
      return Promise.all((names.length ? names : [...resources.keys()]).map((name) => api.load(name)));
    },
    reloadAll() {
      return api.loadAll();
    },
  };
  return api;
}

// ---- status messages --------------------------------------------------------------------

// The messages under one form or one list's actions: `<prefix>-error`, `-uncertain` and
// `-success`, each present only while it applies (plan 3.14). An aria-live region.
export function createStatus(prefix, { success = true } = {}) {
  const region = h('div', { class: 'status', 'aria-live': 'polite' });
  const state = { error: null, uncertain: null, success: null };
  function render() {
    const children = [];
    if (state.error !== null) {
      children.push(h('p', { testid: `${prefix}-error`, class: 'message refused', role: 'alert' }, icon('alert'),
        h('span', {}, state.error)));
    }
    if (state.uncertain !== null) {
      children.push(h('p', { testid: `${prefix}-uncertain`, class: 'message uncertain' }, icon('clock'),
        h('span', {}, state.uncertain)));
    }
    if (success && state.success !== null) {
      children.push(h('div', { testid: `${prefix}-success`, class: 'message success' }, icon('check'),
        h('span', {}, state.success)));
    }
    fill(region, children);
  }
  return {
    region,
    set(changes) {
      Object.assign(state, changes);
      render();
    },
    get state() {
      return state;
    },
  };
}

export const UNCERTAIN_TEXT = 'We could not confirm whether this went through: the money may already have moved. '
  + 'Check the latest figures, or submit again without changing anything: that is safe and cannot move it twice.';
// An item action that moves money (request pay, capture), and one that does not (decline,
// cancel, void).
export const UNCERTAIN_MONEY_ACTION_TEXT = 'We could not confirm whether this went through: the money may already '
  + 'have moved. The list has been refreshed. Check it, or try again without changing anything: that is safe and '
  + 'cannot move the money twice.';
export const UNCERTAIN_ACTION_TEXT = 'We could not confirm whether this went through. '
  + 'The list has been refreshed; if nothing changed, try again.';

// ---- money forms ------------------------------------------------------------------------

// The behaviour of every idempotent money form (D42, D43, D56): validate, keep a retry
// identity, show error, uncertain or success, re-read the screen's data after the response.
//   form     the <form>; its fields fire `input`/`change`
//   button   its submit button: disabled only while its own write is in flight
//   status   createStatus(prefix)
//   build()  -> { body } or { error }
//   send(key, body) -> outcome (api.js)
//   success(data) -> the success message
//   after()  re-reads the data, once the response has arrived
export function moneyForm({ form, button, status, build, send, success, after, screen }) {
  const identity = new RetryIdentity();
  let inFlight = false;
  const touched = () => {
    identity.touch();
    if (status.state.success !== null) status.set({ success: null });
  };
  form.addEventListener('input', touched);
  form.addEventListener('change', touched);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (inFlight) return;
    status.set({ success: null });
    const built = build();
    if (built.error) {
      status.set({ error: built.error });
      return;
    }
    const { key, body } = identity.submission(built.body);
    // A new attempt: the last one's refusal no longer applies. An unknown outcome stays
    // shown until this attempt settles it.
    if (status.state.error !== null) status.set({ error: null });
    inFlight = true;
    button.disabled = true;
    const outcome = await send(key, body);
    inFlight = false;
    button.disabled = false;
    if (!screen.alive) return;
    if (outcome.kind === 'ok') {
      status.set({ error: null, uncertain: null, success: success(outcome.data) });
    } else if (outcome.kind === 'refused') {
      if (outcome.status === 401) return;
      status.set({ error: outcome.message, uncertain: null, success: null });
    } else {
      status.set({ error: null, uncertain: UNCERTAIN_TEXT, success: null });
    }
    await after(outcome);
  });
  return { identity };
}

// One labelled field: <label for> above the control (I46).
let fieldCount = 0;
export function field(label, control, hint) {
  const id = `f${++fieldCount}`;
  control.id = id;
  const hintEl = hint ? h('span', { class: 'hint', id: `${id}-hint` }, hint) : null;
  if (hintEl) control.setAttribute('aria-describedby', `${id}-hint`);
  return h('div', { class: 'field' }, h('label', { for: id }, label), control, hintEl);
}

export function textInput(testid, props = {}) {
  return h('input', { type: 'text', testid, autocomplete: 'off', spellcheck: 'false', ...props });
}

export function amountInput(testid, props = {}) {
  return h('input', { type: 'text', inputmode: 'decimal', testid, autocomplete: 'off', ...props });
}

export function visibilitySelect(testid) {
  return h('select', { testid },
    h('option', { value: 'public' }, 'Public: anyone can see it'),
    h('option', { value: 'private' }, 'Private: only the two of you'));
}

// ---- wallet summary ---------------------------------------------------------------------

// `available` as the headline, `total` and `held` secondary (held absent at 0).
export function walletSummary() {
  const el = h('section', { class: 'card wallet', 'aria-labelledby': 'wallet-title' });
  return {
    el,
    render(me, extra = []) {
      const money = (minor) => formatMoney(minor, me.minor_units, me.currency);
      fill(el,
        h('h2', { id: 'wallet-title', class: 'eyebrow' }, 'Available to spend'),
        h('p', { class: 'headline' },
          h('span', { testid: 'wallet-available', 'data-amount': me.available, class: 'amount' }, money(me.available))),
        h('dl', { class: 'figures' },
          h('div', {}, h('dt', {}, 'Total balance'),
            h('dd', {}, h('span', { testid: 'wallet-balance', 'data-amount': me.total, class: 'amount' }, money(me.total)))),
          me.held > 0
            ? h('div', { class: 'held' }, h('dt', {}, icon('lock'), 'On hold'),
              h('dd', {}, h('span', { testid: 'wallet-held', 'data-amount': me.held, class: 'amount' }, money(me.held))))
            : null),
        extra);
    },
  };
}

// ---- times and parties --------------------------------------------------------------------

const DAY = 86_400_000;
const clockTime = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' });
const dateTime = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });

// "Today, 14:03", "Yesterday, 09:12", "Tomorrow, 10:00" or "4 Oct 2026, 14:03", local time.
export function humanTime(iso) {
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return iso;
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOfDay(t) - startOfDay(new Date())) / DAY);
  const day = days === 0 ? 'Today' : days === -1 ? 'Yesterday' : days === 1 ? 'Tomorrow' : dateTime.format(t);
  return `${day}, ${clockTime.format(t)}`;
}

export function timeEl(iso, props = {}) {
  return h('time', { datetime: iso, ...props }, humanTime(iso));
}

// A handle as people read it, with the viewer marked "you" beside it.
export function party(handle, me) {
  return h('span', { class: 'party' }, `@${handle}`, handle === me.handle ? h('span', { class: 'you' }, ' (you)') : null);
}

export function statusBadge(status) {
  return h('span', { class: `badge ${status}` }, status.charAt(0).toUpperCase() + status.slice(1));
}

export function privateBadge() {
  return h('span', { class: 'badge private' }, icon('lock'), 'Private');
}

// Re-render while keeping keyboard focus on the element with the same data-testid.
export function keepFocus(render) {
  const active = document.activeElement;
  const testid = active?.getAttribute?.('data-testid');
  render();
  if (testid) {
    const again = document.querySelector(`[data-testid="${CSS.escape(testid)}"]`);
    if (again && again !== active && !again.disabled) again.focus({ preventScroll: true });
  }
}

export { call };
