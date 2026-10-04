// W15: GET /statement (windows, order, running balances, pages, known_at) and its snapshots.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, describe, it } from 'node:test';
import { Client, expectError, fixture, login, request, reset, type Server, startServer } from './helpers.ts';

let server: Server;
let port: number;

before(async () => {
  server = await startServer();
  port = server.port;
});
after(() => server.close());

const key = () => randomUUID();
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const microBefore = (ts: string) => new Date(Date.parse(ts) - 1).toISOString().replace('Z', '999Z');
const TOKEN_RE = /^ss_[A-Za-z0-9_-]{14,}$/;
const STATEMENT_FIELDS = ['closing_balance', 'entries', 'has_more', 'opening_balance', 'snapshot'];
const ENTRY_FIELDS = ['balance_after', 'delta', 'effective_at', 'payment', 'recorded_at', 'revision'];
const PAYMENT_FIELDS = [
  'amount', 'authorization_id', 'created_at', 'currency', 'from_handle', 'from_user_id', 'note', 'payment_id',
  'refund_of', 'request_id', 'settlement_id', 'to_handle', 'to_user_id', 'visibility',
];

const q = (params: Record<string, string | number>) =>
  Object.entries(params).map(([n, v]) => `${n}=${encodeURIComponent(String(v))}`).join('&');
async function statementOf(c: Client, params: Record<string, string | number> = {}) {
  const reply = await c.get(`/statement?${q(params)}`);
  assert.equal(reply.status, 200, reply.text);
  return reply.body;
}
const ids = (s: any) => s.entries.map((e: any) => e.payment.payment_id);
const deltas = (s: any) => s.entries.map((e: any) => e.delta);
const afters = (s: any) => s.entries.map((e: any) => e.balance_after);

// Every page of the snapshot, joined.
async function allPages(c: Client, token: string, limit: number) {
  const pages = [];
  for (let offset = 0; ; offset += limit) {
    const page = await statementOf(c, { snapshot: token, limit, offset });
    pages.push(page);
    if (!page.has_more) return pages;
  }
}

describe('statement shape, order and windows (W15.1, W15.2, W15.3)', () => {
  const T0 = '2020-01-01T00:00:00Z';
  let ada: Client;
  let bob: Client;

  before(async () => {
    await reset(port, fixture({
      payments: [
        { id: 'p_b', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 100, created_at: T0, visibility: 'private' },
        { id: 'p_a', from_user_id: 'u_bob', to_user_id: 'u_ada', amount: 50, created_at: '2020-01-01T01:00:00+01:00' },
        { id: '\u{1F600}', from_user_id: 'u_bob', to_user_id: 'u_ada', amount: 1, created_at: T0 },
        { id: '\u{FF5A}', from_user_id: 'u_bob', to_user_id: 'u_ada', amount: 2, created_at: T0 },
        { id: 'p_zero', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 0, created_at: '2020-01-02T00:00:00.000001Z' },
        { id: 'p_other', from_user_id: 'u_bob', to_user_id: 'u_cy', amount: 70, created_at: T0 },
        { id: 'p_late', from_user_id: 'u_cy', to_user_id: 'u_ada', amount: 5, created_at: '2020-01-03T00:00:00Z' },
      ],
    }));
    [ada, bob] = await Promise.all(['ada', 'bob'].map((h) => login(port, h)));
  });

  it('lists the caller\'s payments oldest first, ties by payment_id in code-point order, with running balances', async () => {
    const s = await statementOf(ada);
    assert.deepEqual(Object.keys(s).sort(), STATEMENT_FIELDS);
    assert.match(s.snapshot, TOKEN_RE);
    // Opening: 10000 - (-100 + 50 + 1 + 2 + 0 + 5) = 10042.
    assert.equal(s.opening_balance, 10_042);
    assert.deepEqual(ids(s), ['p_a', 'p_b', '\u{FF5A}', '\u{1F600}', 'p_zero', 'p_late']);
    assert.deepEqual(deltas(s), [50, -100, 2, 1, 0, 5]);
    assert.deepEqual(afters(s), [10_092, 9_992, 9_994, 9_995, 9_995, 10_000]);
    assert.equal(s.closing_balance, 10_000);
    assert.equal(s.has_more, false);
    const [first] = s.entries;
    assert.deepEqual(Object.keys(first).sort(), ENTRY_FIELDS);
    assert.deepEqual(Object.keys(first.payment).sort(), PAYMENT_FIELDS);
    assert.deepEqual([first.revision, first.effective_at, first.recorded_at, first.payment.created_at, first.payment.amount],
      [1, '2020-01-01T01:00:00+01:00', '2020-01-01T01:00:00+01:00', '2020-01-01T01:00:00+01:00', 50]);
    assert.equal(s.entries[1].payment.visibility, 'private', 'the caller\'s private payment appears');
    assert.equal(ids(await statementOf(bob)).includes('p_other'), true);
    assert.equal(ids(s).includes('p_other'), false, 'a public payment between others never appears');
  });

  it('uses the half-open window [from, to)', async () => {
    const s = await statementOf(ada, { from: T0, to: '2020-01-03T00:00:00Z' });
    assert.deepEqual(ids(s), ['p_a', 'p_b', '\u{FF5A}', '\u{1F600}', 'p_zero'], 'in at from, out at to');
    assert.deepEqual([s.opening_balance, s.closing_balance], [10_042, 9_995]);
    const later = await statementOf(ada, { from: '2020-01-01T00:00:00.000001Z', to: '2020-01-03T00:00:00.000001Z' });
    assert.deepEqual(ids(later), ['p_zero', 'p_late']);
    assert.deepEqual([later.opening_balance, afters(later), later.closing_balance], [9_995, [9_995, 10_000], 10_000]);
    const empty = await statementOf(ada, { from: '2020-01-02T00:00:00.000001Z', to: '2020-01-02T00:00:00.000001Z' });
    assert.deepEqual([empty.entries, empty.opening_balance, empty.closing_balance, empty.has_more], [[], 9_995, 9_995, false]);
    const before = await statementOf(ada, { to: '2019-01-01T00:00:00Z' });
    assert.deepEqual([before.entries, before.opening_balance, before.closing_balance], [[], 10_042, 10_042]);
    const future = await statementOf(ada, { from: '2030-01-01T00:00:00Z', to: '9999-12-31T23:59:59Z' });
    assert.deepEqual([future.entries, future.opening_balance, future.closing_balance], [[], 10_000, 10_000]);
    // A future from with to omitted: an empty window at the balance of the read (D72).
    const ahead = await statementOf(ada, { from: '9999-12-31T23:59:59Z', limit: 1 });
    const total = (await ada.get('/me')).body.total;
    assert.deepEqual([ahead.entries, ahead.opening_balance, ahead.closing_balance, ahead.has_more], [[], total, total, false]);
    assert.deepEqual(await statementOf(ada, { snapshot: ahead.snapshot, limit: 1 }), ahead);
    const fromOnly = await statementOf(ada, { from: '2020-01-02T00:00:00+00:00' });
    assert.deepEqual(ids(fromOnly), ['p_zero', 'p_late']);
    // A literal + in the query is a plus sign.
    const raw = await ada.get('/statement?from=2020-01-01T01:00:00+01:00&to=2020-01-03T00:00:00+00:00');
    assert.equal(raw.status, 200, raw.text);
    assert.deepEqual(ids(raw.body), ids(s));
  });

  it('refuses invalid instants and from later than to with 422', async () => {
    for (const params of [
      { from: '' }, { to: '' }, { known_at: '' }, { from: '2020-01-01' }, { to: '2020-01-01T00:00:00' },
      { from: '2020-02-30T00:00:00Z' }, { to: '2020-01-01T24:00:00Z' }, { known_at: '2020-01-01T00:00:00+24:00' },
      { from: '2020-01-02T00:00:00Z', to: '2020-01-01T23:59:59.999999Z' }, { from: '9999-12-31T23:59:59Z', to: '9999-12-31T23:59:58Z' },
      { limit: 0 }, { limit: 201 }, { limit: 'x' }, { offset: -1 }, { offset: '1.0' },
    ] as Record<string, string | number>[]) {
      expectError(await ada.get(`/statement?${q(params)}`), 422, 'validation_failed');
    }
    expectError(await request(port, 'GET', '/statement'), 401, 'unauthenticated');
    expectError(await request(port, 'GET', '/statement?from=bad'), 401, 'unauthenticated');
  });

  it('includes a payment made just before the read in the default window', async () => {
    for (let i = 0; i < 5; i++) {
      const paid = (await ada.post('/payments', { json: { to_handle: 'bob', amount: 1 }, key: key() })).body;
      const s = await statementOf(ada);
      assert.equal(ids(s).at(-1), paid.payment_id);
      assert.equal(s.closing_balance, (await ada.get('/me')).body.total);
    }
  });
});

describe('pages and snapshots (W15.4, W15.5, W15.6)', () => {
  it('pages exactly as GET /requests, every page with the full window balances', async () => {
    await reset(port, fixture());
    const ada = await login(port, 'ada');
    for (let i = 1; i <= 7; i++) await ada.post('/payments', { json: { to_handle: 'bob', amount: i }, key: key() });
    const whole = await statementOf(ada);
    assert.deepEqual(deltas(whole), [-1, -2, -3, -4, -5, -6, -7]);
    const pages = await allPages(ada, whole.snapshot, 3);
    assert.deepEqual(pages.map((p) => [ids(p).length, p.has_more]), [[3, true], [3, true], [1, false]]);
    assert.deepEqual(pages.flatMap(ids), ids(whole));
    assert.deepEqual(pages.flatMap(afters), afters(whole));
    for (const p of pages) {
      assert.deepEqual([p.opening_balance, p.closing_balance, p.snapshot], [10_000, 9_972, whole.snapshot]);
      assert.deepEqual(Object.keys(p).sort(), STATEMENT_FIELDS);
    }
    const first = await statementOf(ada, { limit: 3, offset: 4 });
    assert.deepEqual([deltas(first), afters(first), first.has_more], [[-5, -6, -7], [9_985, 9_979, 9_972], false]);
    assert.notEqual(first.snapshot, whole.snapshot, 'every first read stores a new snapshot');
    const exact = await statementOf(ada, { snapshot: whole.snapshot, limit: 7 });
    assert.deepEqual([exact.entries.length, exact.has_more], [7, false]);
    const past = await statementOf(ada, { snapshot: whole.snapshot, offset: 7 });
    assert.deepEqual([past.entries, past.has_more, past.closing_balance], [[], false, 9_972]);
    const far = await statementOf(ada, { offset: 1000 });
    assert.deepEqual([far.entries, far.has_more], [[], false]);
    for (const params of [{ limit: 0 }, { limit: 201 }, { limit: '+1' }, { offset: 'x' }, { offset: '' }] as Record<string, string | number>[]) {
      expectError(await ada.get(`/statement?${q({ snapshot: whole.snapshot, ...params })}`), 422, 'validation_failed');
    }
  });

  it('freezes the first result against everything that happens afterwards', async () => {
    await reset(port, fixture({ settlement_operator_ids: ['u_ada'], authorization_ttl_seconds: 1 }));
    const [ada, bob] = await Promise.all(['ada', 'bob'].map((h) => login(port, h)));
    await ada.post('/payments', { json: { to_handle: 'bob', amount: 10 }, key: key() });
    const hold = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 500 }, key: key() })).body;
    const capture = (await bob.post(`/authorizations/${hold.authorization_id}/capture`, { json: { amount: 40, final: false }, key: key() })).body;
    const first = await statementOf(ada, { limit: 1 });
    const firstFull = await statementOf(ada, { snapshot: first.snapshot, limit: 200 });
    assert.deepEqual(deltas(firstFull), [-10, -40], 'holds are never entries; the capture is one');
    assert.equal(firstFull.entries[1].payment.authorization_id, hold.authorization_id);
    const openEnded = await statementOf(ada, { to: '9999-12-31T23:59:59.999999999Z', limit: 200 });
    assert.deepEqual(deltas(openEnded), [-10, -40]);

    // Everything else that can happen to ada's wallet.
    await ada.post('/payments', { json: { to_handle: 'bob', amount: 1 }, key: key() });
    await bob.post('/payments', { json: { to_handle: 'ada', amount: 2 }, key: key() });
    const req = (await bob.post('/requests', { json: { payer_handle: 'ada', amount: 3 }, key: key() })).body;
    await ada.post(`/requests/${req.request_id}/pay`, { json: {}, key: key() });
    await ada.post('/settlements', { json: { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 4 }] }, key: key() });
    await bob.post(`/authorizations/${hold.authorization_id}/capture`, { json: { amount: 5, final: true }, key: key() });
    const voided = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 6 }, key: key() })).body;
    await ada.post(`/authorizations/${voided.authorization_id}/void`);
    await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 7 }, key: key() });
    await sleep(1_100); // the last hold expires

    assert.deepEqual(await statementOf(ada, { snapshot: first.snapshot, limit: 1 }), first);
    assert.deepEqual(await statementOf(ada, { snapshot: first.snapshot, limit: 200 }), firstFull);
    // A window reaching into the future holds the later payments' times, yet its snapshot does
    // not show them.
    assert.deepEqual(await statementOf(ada, { snapshot: openEnded.snapshot, limit: 200 }), openEnded);
    const now = await statementOf(ada, { limit: 200 });
    assert.deepEqual(deltas(now), [-10, -40, -1, 2, -3, -4, -5]);
    assert.equal(now.closing_balance, (await ada.get('/me')).body.total);
  });

  it('refuses window parameters with a snapshot, and answers 404 for unknown, foreign and reset tokens', async () => {
    await reset(port, fixture());
    const [ada, bob] = await Promise.all(['ada', 'bob'].map((h) => login(port, h)));
    const { snapshot } = await statementOf(ada);
    for (const extra of [{ from: '2020-01-01T00:00:00Z' }, { to: '2020-01-01T00:00:00Z' }, { known_at: '2020-01-01T00:00:00Z' }, { from: 'bad' }, { to: '' }]) {
      expectError(await ada.get(`/statement?${q({ snapshot, ...extra })}`), 422, 'validation_failed');
    }
    expectError(await ada.get(`/statement?known_at&snapshot=${snapshot}`), 422, 'validation_failed');
    expectError(await bob.get(`/statement?snapshot=${snapshot}`), 404, 'not_found');
    for (const token of ['ss_nothing', '', 'x'.repeat(5000), `${snapshot}x`, snapshot.toUpperCase()]) {
      expectError(await ada.get(`/statement?${q({ snapshot: token })}`), 404, 'not_found');
    }
    expectError(await ada.get('/statement?snapshot'), 404, 'not_found');
    expectError(await request(port, 'GET', `/statement?snapshot=${snapshot}`), 401, 'unauthenticated');
    assert.equal((await ada.get(`/statement?snapshot=${snapshot}&as_of=2020-01-01&direction=x`)).status, 200, 'unknown parameters are ignored');
    await reset(port, fixture());
    const again = await login(port, 'ada');
    expectError(await again.get(`/statement?snapshot=${snapshot}`), 404, 'not_found');
  });

  it('leaves out payments recorded after known_at and echoes it on every page', async () => {
    await reset(port, fixture({ payments: [{ id: 'p_seed', from_user_id: 'u_bob', to_user_id: 'u_ada', amount: 25, created_at: '2020-01-01T00:00:00Z' }] }));
    const ada = await login(port, 'ada');
    const one = (await ada.post('/payments', { json: { to_handle: 'bob', amount: 1 }, key: key() })).body;
    const two = (await ada.post('/payments', { json: { to_handle: 'bob', amount: 2 }, key: key() })).body;
    const K = microBefore(two.created_at).replace('Z', '+00:00');
    const s = await statementOf(ada, { known_at: K, limit: 1 });
    assert.deepEqual(Object.keys(s).sort(), [...STATEMENT_FIELDS, 'known_at'].sort());
    assert.equal(s.known_at, K);
    const full = await statementOf(ada, { snapshot: s.snapshot });
    assert.deepEqual([ids(full), full.known_at, full.opening_balance, full.closing_balance],
      [['p_seed', one.payment_id], K, 9_975, 9_999]);
    const page2 = await statementOf(ada, { snapshot: s.snapshot, limit: 1, offset: 1 });
    assert.deepEqual([ids(page2), page2.known_at, afters(page2)], [[one.payment_id], K, [9_999]]);
    const early = await statementOf(ada, { known_at: '2019-12-31T23:59:59Z' });
    assert.deepEqual([early.entries, early.opening_balance, early.closing_balance, early.known_at], [[], 9_975, 9_975, '2019-12-31T23:59:59Z']);
    const raw = await ada.get(`/statement?known_at=${K}`);
    assert.equal(raw.body.known_at, K, 'a raw + is a plus sign');
    assert.equal('known_at' in (await statementOf(ada)), false);
  });
});
