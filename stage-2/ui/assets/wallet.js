// The wallet screen `/`: the wallet numbers, the pay, request and authorize forms, and the
// activity feed (plan 3.14 "Screens", W10).

import { call, readAll } from './api.js';
import { fill, h, icon } from './dom.js';
import { authorizeForm } from './holds.js';
import {
  amountInput, createLoads, createStatus, field, keepFocus, moneyForm, party, privateBadge, textInput, timeEl,
  visibilitySelect, walletSummary,
} from './kit.js';
import { formatMoney, parseAmount } from './money.js';
import { cleanHandle } from './split.js';

const MAX_NOTE = 200;
export const noteTooLong = (note) => [...note].length > MAX_NOTE;

export function walletScreen(main, ctx) {
  const statusRegion = h('div', { class: 'load-status' });
  const loads = createLoads(ctx, statusRegion);
  const summary = walletSummary();
  const formsCol = h('div', { class: 'column forms' });
  const feedSection = h('section', { class: 'card feed', 'aria-labelledby': 'feed-title' });
  let me = null;
  let feed = null;
  let formsBuilt = false;

  const refresh = () => loads.loadAll('me', 'activity');
  const refreshButton = h('button', { type: 'button', testid: 'wallet-refresh', class: 'button secondary small', onclick: refresh },
    icon('refresh'), 'Refresh');

  loads.add('me', () => call('GET', '/me'), (data) => {
    me = data;
    ctx.showUser(data);
    summary.render(data, h('div', { class: 'wallet-actions' }, refreshButton,
      ctx.link('/authorizations', { class: 'text-link' }, icon('hold'), 'Holds')));
    if (!formsBuilt) {
      formsBuilt = true;
      formsCol.append(payForm(), requestForm(), authorizeForm(ctx, () => me, refresh));
    }
    if (feed) renderFeed();
  });
  loads.add('activity', () => readAll('/activity', 'payments', (p) => p.payment_id), (items) => {
    feed = items;
    if (me) renderFeed();
  });

  function renderFeed() {
    keepFocus(() => fill(feedSection,
      h('div', { class: 'section-head' }, h('h2', { id: 'feed-title' }, 'Activity')),
      feed.length === 0
        ? h('div', { testid: 'empty-activity', class: 'empty-state' },
          h('p', {}, 'No activity yet.'),
          h('p', { class: 'muted' }, 'Payments you send or receive, and public payments between others, will show here. '
            + 'Send your first payment with the form.'))
        : h('ul', { testid: 'activity-list', class: 'list' }, feed.map((p) => feedItem(p, me)))));
  }

  function payForm() {
    const handle = textInput('pay-handle', { autocapitalize: 'none', placeholder: 'e.g. bob' });
    const amount = amountInput('pay-amount', { placeholder: me.minor_units === 0 ? 'e.g. 15' : 'e.g. 15.00' });
    const note = textInput('pay-note', { placeholder: 'e.g. Dinner' });
    const visibility = visibilitySelect('pay-visibility');
    const button = h('button', { type: 'submit', testid: 'pay-submit', class: 'button wide' }, 'Send money');
    const status = createStatus('pay');
    const form = h('form', { class: 'stack', novalidate: true },
      field('To (handle)', handle), field(`Amount (${me.currency})`, amount), field('Note (optional)', note),
      field('Who can see it', visibility), status.region, button);
    moneyForm({
      form, button, status, screen: ctx,
      build: () => {
        const to = cleanHandle(handle.value);
        if (!to) return { error: 'Enter the handle of the person to pay.' };
        const parsed = parseAmount(amount.value, me.minor_units);
        if (parsed.error) return { error: parsed.error };
        if (noteTooLong(note.value)) return { error: `A note can be at most ${MAX_NOTE} characters.` };
        const body = { to_handle: to, amount: parsed.value };
        if (note.value !== '') body.note = note.value;
        body.visibility = visibility.value;
        return { body };
      },
      send: (key, body) => call('POST', '/payments', { body, key }),
      success: (p) => `Sent ${formatMoney(p.amount, me.minor_units, me.currency)} to @${p.to_handle}.`,
      after: refresh,
    });
    return h('section', { class: 'card', 'aria-labelledby': 'pay-title' }, h('h2', { id: 'pay-title' }, 'Send money'), form);
  }

  function requestForm() {
    const handle = textInput('request-handle', { autocapitalize: 'none', placeholder: 'e.g. cy' });
    const amount = amountInput('request-amount', { placeholder: me.minor_units === 0 ? 'e.g. 15' : 'e.g. 15.00' });
    const note = textInput('request-note', { placeholder: 'e.g. Concert tickets' });
    const button = h('button', { type: 'submit', testid: 'request-submit', class: 'button secondary wide' }, 'Request money');
    const status = createStatus('request');
    const form = h('form', { class: 'stack', novalidate: true },
      field('From (handle)', handle), field(`Amount (${me.currency})`, amount), field('Note (optional)', note),
      status.region, button);
    moneyForm({
      form, button, status, screen: ctx,
      build: () => {
        const from = cleanHandle(handle.value);
        if (!from) return { error: 'Enter the handle of the person to ask.' };
        const parsed = parseAmount(amount.value, me.minor_units);
        if (parsed.error) return { error: parsed.error };
        if (noteTooLong(note.value)) return { error: `A note can be at most ${MAX_NOTE} characters.` };
        const body = { payer_handle: from, amount: parsed.value };
        if (note.value !== '') body.note = note.value;
        return { body };
      },
      send: (key, body) => call('POST', '/requests', { body, key }),
      success: (r) => `Requested ${formatMoney(r.amount, me.minor_units, me.currency)} from @${r.payer_handle}. `
        + 'It is waiting for them on their Requests page.',
      after: refresh,
    });
    return h('section', { class: 'card', 'aria-labelledby': 'request-title' }, h('h2', { id: 'request-title' }, 'Request money'), form);
  }

  main.append(
    h('h1', { class: 'visually-hidden' }, 'Wallet'),
    statusRegion,
    h('div', { class: 'wallet-layout' }, h('div', { class: 'column' }, summary.el, formsCol), feedSection),
  );
  refresh();
  return {};
}

// One payment in the feed, from the viewer's side: direction, parties, note, time, amount.
export function feedItem(p, me) {
  const id = p.payment_id;
  const sent = p.from_handle === me.handle;
  const received = p.to_handle === me.handle;
  const direction = sent ? 'Sent' : received ? 'Received' : 'Between others';
  const kind = p.authorization_id ? 'From a hold' : p.request_id ? 'Request paid' : p.settlement_id ? 'Settlement' : null;
  return h('li', { testid: `activity-item-${id}`, 'data-visibility': p.visibility, class: `item ${sent ? 'out' : received ? 'in' : 'other'}` },
    h('div', { class: 'item-main' },
      h('p', { class: 'item-meta' }, h('span', { class: 'direction' }, direction),
        kind ? h('span', { class: 'badge neutral' }, kind) : null,
        p.visibility === 'private' ? privateBadge() : null),
      h('p', { testid: `activity-parties-${id}`, class: 'parties' }, party(p.from_handle, me), ' → ', party(p.to_handle, me)),
      h('p', { testid: `activity-note-${id}`, class: 'note' }, p.note),
      h('p', { class: 'item-time' }, timeEl(p.created_at))),
    h('p', { class: 'item-amount' },
      h('span', { class: 'sign', 'aria-hidden': 'true' }, sent ? '−' : received ? '+' : ''),
      h('span', { testid: `activity-amount-${id}`, class: 'amount' }, formatMoney(p.amount, me.minor_units, me.currency))));
}
