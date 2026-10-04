// The split screen `/split`: the split form, a live preview by the §9 rule and, after success,
// a summary of the requests created (W11.2).

import { call } from './api.js';
import { fill, h, icon } from './dom.js';
import { amountInput, createLoads, createStatus, field, moneyForm, textInput } from './kit.js';
import { formatMoney, parseAmount } from './money.js';
import { equalShares, parseHandles } from './split.js';

const MAX_NOTE = 200;

export function splitScreen(main, ctx) {
  const statusRegion = h('div', { class: 'load-status' });
  const loads = createLoads(ctx, statusRegion);
  const formSlot = h('div', { class: 'split-layout' });
  let me = null;

  loads.add('me', () => call('GET', '/me'), (data) => {
    me = data;
    ctx.showUser(data);
    if (formSlot.childElementCount === 0) formSlot.append(splitForm());
  });

  function splitForm() {
    const amount = amountInput('split-amount', { placeholder: me.minor_units === 0 ? 'e.g. 3000' : 'e.g. 30.00' });
    const handles = textInput('split-handles', { autocapitalize: 'none', placeholder: `e.g. ${me.handle}, bob, cy` });
    const note = textInput('split-note', { placeholder: 'e.g. Dinner at Luigi’s' });
    const button = h('button', { type: 'submit', testid: 'split-submit', class: 'button wide' }, 'Split and send requests');
    const status = createStatus('split');
    const preview = h('div', { class: 'preview-slot', 'aria-live': 'polite' });
    const form = h('form', { class: 'stack', novalidate: true },
      field(`Total amount (${me.currency})`, amount),
      field('People, in order', handles, 'Handles separated by commas. Include yourself to pay a share too.'),
      field('Note (optional)', note),
      preview, status.region, button);

    const money = (minor) => formatMoney(minor, me.minor_units, me.currency);
    const parsed = () => {
      const a = parseAmount(amount.value, me.minor_units);
      const list = parseHandles(handles.value);
      return { a, list };
    };
    function renderPreview() {
      const { a, list } = parsed();
      if (a.error || list.error) {
        fill(preview);
        return;
      }
      const shares = equalShares(a.value, list.handles.length);
      fill(preview, h('div', { testid: 'split-preview', class: 'preview' },
        h('p', { class: 'eyebrow' }, 'Each person pays'),
        h('ul', { class: 'shares' }, list.handles.map((handle, i) => h('li', {},
          h('span', { class: 'party' }, `@${handle}`, handle === me.handle ? h('span', { class: 'you' }, ' (you)') : null),
          h('span', { testid: `split-share-${handle}`, class: 'amount' }, money(shares[i])))))));
    }
    form.addEventListener('input', renderPreview);
    form.addEventListener('change', renderPreview);

    moneyForm({
      form, button, status, screen: ctx,
      build: () => {
        const { a, list } = parsed();
        if (a.error) return { error: a.error };
        if (list.error) return { error: list.error };
        if ([...note.value].length > MAX_NOTE) return { error: `A note can be at most ${MAX_NOTE} characters.` };
        const body = { amount: a.value, participant_handles: list.handles };
        if (note.value !== '') body.note = note.value;
        return { body };
      },
      send: (key, body) => call('POST', '/splits', { body, key }),
      success: (split) => {
        const asked = split.requests.map((r) => `@${r.payer_handle} ${money(r.amount)}`);
        return `Split ${money(split.amount)}. ${asked.length
          ? `Requests sent: ${asked.join(', ')}.`
          : 'Nobody else was asked to pay.'}`;
      },
      after: () => loads.loadAll('me'),
    });
    return h('section', { class: 'card', 'aria-labelledby': 'split-title' },
      h('p', { class: 'muted' }, 'Share a bill equally. Everyone else listed gets a request for their share.'),
      form);
  }

  main.append(h('h1', { class: 'page-title', id: 'split-title' }, icon('split'), 'Split a bill'), statusRegion, formSlot);
  loads.loadAll();
  return {};
}
