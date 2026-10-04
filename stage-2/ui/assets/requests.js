// The requests screen `/requests`: incoming and outgoing requests of every status, with pay
// and decline on pending incoming ones and cancel on pending outgoing ones (W11.1).

import { call, readAll } from './api.js';
import { fill, h, icon } from './dom.js';
import {
  createLoads, createStatus, keepFocus, party, statusBadge, timeEl, UNCERTAIN_ACTION_TEXT,
} from './kit.js';
import { formatMoney } from './money.js';
import { newKey } from './retry.js';

export function requestsScreen(main, ctx) {
  const statusRegion = h('div', { class: 'load-status' });
  const loads = createLoads(ctx, statusRegion);
  const lists = h('div', { class: 'requests-layout' });
  const actions = createStatus('request', { success: false });
  let me = null;
  let requests = null;
  const inFlight = new Set();
  const payKeys = new Map(); // request id -> the key of its payment, kept for retries
  let pending = null; // { id, expect } after an unknown outcome
  let concerns = null; // the id of the request the latest action's messages are about

  const reload = () => loads.loadAll('me', 'requests');
  loads.add('me', () => call('GET', '/me'), (data) => {
    me = data;
    ctx.showUser(data);
    if (requests) render();
  });
  loads.add('requests', () => readAll('/requests', 'requests', (r) => r.request_id), (data) => {
    requests = data;
    if (pending) {
      const now = requests.find((r) => r.request_id === pending.id);
      if (now && now.status === pending.expect) {
        actions.set({ uncertain: null });
        pending = null;
      }
    }
    if (me) render();
  });

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

  const pay = (id) => {
    if (!payKeys.has(id)) payKeys.set(id, newKey());
    return act(id, 'paid', () => call('POST', `/requests/${encodeURIComponent(id)}/pay`, { body: {}, key: payKeys.get(id) }));
  };
  const decline = (id) => act(id, 'declined', () => call('POST', `/requests/${encodeURIComponent(id)}/decline`));
  const cancel = (id) => act(id, 'cancelled', () => call('POST', `/requests/${encodeURIComponent(id)}/cancel`));

  function item(r, incoming) {
    const id = r.request_id;
    const busy = inFlight.has(id);
    const pendingNow = r.status === 'pending';
    const buttons = [];
    if (pendingNow && incoming) {
      buttons.push(
        h('button', { type: 'button', testid: `request-pay-${id}`, class: 'button small', disabled: busy, onclick: () => pay(id) }, 'Pay'),
        h('button', { type: 'button', testid: `request-decline-${id}`, class: 'button secondary small', disabled: busy, onclick: () => decline(id) },
          'Decline'));
    } else if (pendingNow) {
      buttons.push(h('button', {
        type: 'button', testid: `request-cancel-${id}`, class: 'button secondary small', disabled: busy, onclick: () => cancel(id),
      }, 'Cancel request'));
    }
    // The item's colour follows the money, as in the feed: a request you would pay is money out (W13.1).
    return h('li', { testid: `request-item-${id}`, 'data-status': r.status, class: `item ${incoming ? 'out' : 'in'}` },
      h('div', { class: 'item-main' },
        h('p', { class: 'item-meta' },
          h('span', { class: 'direction' }, incoming ? 'Asks you to pay' : 'You asked to be paid'), statusBadge(r.status)),
        h('p', { class: 'parties' }, party(incoming ? r.requester_handle : r.payer_handle, me)),
        r.note ? h('p', { class: 'note' }, r.note) : null,
        h('p', { class: 'item-time' }, timeEl(r.created_at)),
        buttons.length ? h('div', { class: 'item-actions' }, buttons) : null),
      h('p', { class: 'item-amount' },
        h('span', { testid: `request-amount-${id}`, class: 'amount' }, formatMoney(r.amount, me.minor_units, me.currency))));
  }

  function render() {
    if (!me || !requests) return;
    const incoming = requests.filter((r) => r.payer_id === me.user_id);
    const outgoing = requests.filter((r) => r.requester_id === me.user_id);
    // An action's messages sit at the request they concern, or above the lists when it is not shown.
    const atItem = requests.some((r) => r.request_id === concerns);
    const itemWithMessages = (r, isIncoming) => {
      const li = item(r, isIncoming);
      if (atItem && r.request_id === concerns) li.append(h('div', { class: 'item-row' }, actions.region));
      return li;
    };
    keepFocus(() => fill(lists,
      atItem ? null : actions.region,
      incoming.length === 0 && outgoing.length === 0
        ? h('div', { testid: 'empty-requests', class: 'card empty-state' },
          h('p', {}, 'No requests yet.'),
          h('p', { class: 'muted' }, 'Ask someone for money from your wallet, or split a bill.'),
          h('p', {}, ctx.link('/split', { class: 'text-link' }, icon('split'), 'Split a bill')))
        : null,
      h('section', { class: 'card', 'aria-labelledby': 'incoming-title' },
        h('h2', { id: 'incoming-title' }, 'Asked of you'),
        h('ul', { testid: 'incoming-list', class: 'list', 'data-empty': 'Nobody has asked you for money.' },
          incoming.map((r) => itemWithMessages(r, true)))),
      h('section', { class: 'card', 'aria-labelledby': 'outgoing-title' },
        h('h2', { id: 'outgoing-title' }, 'You asked'),
        h('ul', { testid: 'outgoing-list', class: 'list', 'data-empty': 'You have not asked anyone for money.' },
          outgoing.map((r) => itemWithMessages(r, false))))));
  }

  main.append(h('h1', { class: 'page-title' }, icon('requests'), 'Requests'), statusRegion, lists);
  reload();
  return {};
}
