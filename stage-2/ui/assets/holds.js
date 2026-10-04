// Holds: the authorize form (on `/` and `/authorizations`, D46) and the screen
// `/authorizations` with the wallet summary and every hold in both directions (W11.3).

import { call, readAll } from './api.js';
import { fill, h, icon } from './dom.js';
import {
  amountInput, createLoads, createStatus, field, keepFocus, moneyForm, party, privateBadge, statusBadge, textInput,
  timeEl, UNCERTAIN_ACTION_TEXT, visibilitySelect, walletSummary,
} from './kit.js';
import { decimalText, formatMoney, parseAmount } from './money.js';
import { RetryIdentity } from './retry.js';
import { cleanHandle } from './split.js';

const MAX_NOTE = 200;

// The authorize form: same input rules as the pay form. `getMe()` gives the latest GET /me.
export function authorizeForm(ctx, getMe, after) {
  const me = getMe();
  const handle = textInput('authorize-handle', { autocapitalize: 'none', placeholder: 'e.g. bob' });
  const amount = amountInput('authorize-amount', { placeholder: me.minor_units === 0 ? 'e.g. 20' : 'e.g. 20.00' });
  const note = textInput('authorize-note', { placeholder: 'e.g. Deposit' });
  const visibility = visibilitySelect('authorize-visibility');
  const button = h('button', { type: 'submit', testid: 'authorize-submit', class: 'button secondary wide' }, 'Place hold');
  const status = createStatus('authorize');
  const form = h('form', { class: 'stack', novalidate: true },
    field('For (handle)', handle), field(`Amount (${me.currency})`, amount), field('Note (optional)', note),
    field('Who can see the payment', visibility), status.region, button);
  moneyForm({
    form, button, status, screen: ctx,
    build: () => {
      const m = getMe();
      const to = cleanHandle(handle.value);
      if (!to) return { error: 'Enter the handle of the person the hold is for.' };
      const parsed = parseAmount(amount.value, m.minor_units);
      if (parsed.error) return { error: parsed.error };
      if ([...note.value].length > MAX_NOTE) return { error: `A note can be at most ${MAX_NOTE} characters.` };
      const body = { to_handle: to, amount: parsed.value };
      if (note.value !== '') body.note = note.value;
      body.visibility = visibility.value;
      return { body };
    },
    send: (key, body) => call('POST', '/authorizations', { body, key }),
    success: (a) => {
      const m = getMe();
      return `Placed a hold of ${formatMoney(a.amount, m.minor_units, m.currency)} for @${a.to_handle}. `
        + `It is reserved, not sent, until @${a.to_handle} captures it or it expires.`;
    },
    after,
  });
  return h('section', { class: 'card', 'aria-labelledby': 'authorize-title' },
    h('h2', { id: 'authorize-title' }, 'Place a hold'),
    h('p', { class: 'muted' }, 'Reserve money for someone now; they collect it later, all or part of it.'),
    form);
}

export function holdsScreen(main, ctx) {
  const statusRegion = h('div', { class: 'load-status' });
  const loads = createLoads(ctx, statusRegion);
  const summary = walletSummary();
  const formSlot = h('div', {});
  const listSection = h('section', { class: 'card', 'aria-labelledby': 'holds-title' });
  const actions = createStatus('authorization', { success: false });
  let me = null;
  let items = null;
  const inFlight = new Set(); // authorization ids with a capture or void on the way
  const captures = new Map(); // id -> { text, edited, identity }: the capture inputs survive re-renders
  let pending = null; // { id, expect } after an unknown outcome: resolved when a re-read shows it
  let concerns = null; // the id of the hold the latest action's messages are about

  const reload = () => loads.loadAll('me', 'list');
  loads.add('me', () => call('GET', '/me'), (data) => {
    me = data;
    ctx.showUser(data);
    summary.render(data);
    if (formSlot.childElementCount === 0) formSlot.append(authorizeForm(ctx, () => me, reload));
    if (items) render();
  });
  loads.add('list', () => readAll('/authorizations', 'authorizations', (a) => a.authorization_id), (data) => {
    items = data;
    if (pending) {
      const now = items.find((a) => a.authorization_id === pending.id);
      if (now && now.status === pending.expect) {
        actions.set({ uncertain: null });
        pending = null;
      }
    }
    if (me) render();
  });

  function captureState(a) {
    const remaining = decimalText(a.remaining_amount, me.minor_units);
    let state = captures.get(a.authorization_id);
    if (!state) {
      state = { text: remaining, edited: false, identity: new RetryIdentity() };
      captures.set(a.authorization_id, state);
    }
    if (!state.edited) state.text = remaining; // re-filled with the latest remainder
    return state;
  }

  async function capture(a) {
    const state = captureState(a);
    const parsed = parseAmount(state.text, me.minor_units);
    if (parsed.error) {
      concerns = a.authorization_id;
      actions.set({ error: parsed.error });
      render();
      return;
    }
    const { key, body } = state.identity.submission({ amount: parsed.value });
    await act(a.authorization_id, 'captured',
      () => call('POST', `/authorizations/${encodeURIComponent(a.authorization_id)}/capture`, { body, key }));
  }

  async function act(id, expect, send) {
    inFlight.add(id);
    concerns = id;
    render();
    const outcome = await send();
    inFlight.delete(id);
    if (!ctx.alive) return;
    if (outcome.kind === 'ok') {
      actions.set({ error: null, uncertain: null });
      pending = null;
    } else if (outcome.kind === 'refused') {
      if (outcome.status === 401) return;
      actions.set({ error: outcome.message, uncertain: null });
    } else {
      actions.set({ error: null, uncertain: UNCERTAIN_ACTION_TEXT });
      pending = { id, expect };
    }
    render();
    await reload();
  }

  function item(a) {
    const id = a.authorization_id;
    const outgoing = a.from_user_id === me.user_id;
    const money = (minor) => formatMoney(minor, me.minor_units, me.currency);
    const open = a.status === 'open';
    const busy = inFlight.has(id);
    let controls = null;
    if (open && !outgoing) {
      const state = captureState(a);
      const input = amountInput(`authorization-capture-amount-${id}`, { value: state.text });
      input.addEventListener('input', () => {
        state.text = input.value;
        state.edited = true;
        state.identity.touch();
      });
      const form = h('form', { class: 'capture', novalidate: true },
        field('Amount to collect', input),
        h('button', { type: 'submit', testid: `authorization-capture-${id}`, class: 'button small', disabled: busy }, 'Collect'));
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        if (!inFlight.has(id)) capture(a);
      });
      controls = form;
    } else if (open && outgoing) {
      controls = h('div', { class: 'item-actions' },
        h('button', {
          type: 'button', testid: `authorization-void-${id}`, class: 'button secondary small', disabled: busy,
          onclick: () => act(id, 'voided', () => call('POST', `/authorizations/${encodeURIComponent(id)}/void`)),
        }, 'Release hold'));
    }
    return h('li', { testid: `authorization-item-${id}`, 'data-status': a.status, class: `item hold ${outgoing ? 'out' : 'in'}` },
      h('div', { class: 'item-main' },
        h('p', { class: 'item-meta' },
          h('span', { class: 'direction' }, outgoing ? 'You are holding for' : 'Held for you by'),
          statusBadge(a.status), a.visibility === 'private' ? privateBadge() : null),
        h('p', { class: 'parties' }, party(outgoing ? a.to_handle : a.from_handle, me)),
        a.note ? h('p', { class: 'note' }, a.note) : null),
      h('p', { class: 'item-amount' },
        h('span', { testid: `authorization-amount-${id}`, class: 'amount' }, money(a.amount))),
      // Full-width rows under the item, so the expiry text has the card's width (W13.2).
      h('dl', { class: 'facts item-row' },
        h('div', {}, h('dt', {}, 'Captured'), h('dd', {},
          a.status === 'captured'
            ? h('span', { testid: `authorization-captured-${id}`, class: 'amount' }, money(a.captured_amount))
            : h('span', { class: 'amount' }, money(a.captured_amount)))),
        h('div', {}, h('dt', {}, 'Still held'), h('dd', {}, h('span', { class: 'amount' }, money(a.remaining_amount)))),
        h('div', { class: 'expiry' }, h('dt', {}, open ? 'Expires' : 'Expiry'), h('dd', {},
          h('span', { testid: `authorization-expires-${id}`, class: 'mono instant' }, a.expires_at),
          ' ', h('span', { class: 'muted human-time' }, '(', timeEl(a.expires_at), ')')))),
      controls ? h('div', { class: 'item-row' }, controls) : null);
  }

  function render() {
    if (!me || !items) return;
    // An action's messages sit at the hold they concern, or above the list when it is not shown.
    const atItem = items.some((a) => a.authorization_id === concerns);
    const itemWithMessages = (a) => {
      const li = item(a);
      if (atItem && a.authorization_id === concerns) li.append(h('div', { class: 'item-row' }, actions.region));
      return li;
    };
    keepFocus(() => fill(listSection,
      h('div', { class: 'section-head' }, h('h2', { id: 'holds-title' }, 'Your holds')),
      atItem ? null : actions.region,
      items.length === 0
        ? h('div', { testid: 'empty-authorizations', class: 'empty-state' },
          h('p', {}, 'No holds yet.'),
          h('p', { class: 'muted' }, 'Place a hold to reserve money for someone; holds others place for you appear here too.'))
        : null,
      h('ul', { testid: 'authorization-list', class: 'list' }, items.map(itemWithMessages))));
  }

  main.append(
    h('h1', { class: 'page-title' }, icon('hold'), 'Holds'),
    statusRegion,
    h('div', { class: 'holds-layout' }, h('div', { class: 'column' }, summary.el, formSlot), listSection),
  );
  reload();
  return {};
}
