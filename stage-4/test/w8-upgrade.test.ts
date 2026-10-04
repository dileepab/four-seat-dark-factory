// W8: export schema 2, stage-2 round trips, and the upgrade from a stage-1 export.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, beforeEach, describe, it } from 'node:test';
import {
  Client, expectError, fixture, login, PASSWORD, request, reset, startProcess, startServer, user,
  type Server,
} from './helpers.ts';

let server: Server;
let second: Server; // another stage-2 process
let previous: Server; // the frozen stage-1 build, the previous service of the upgrade
let port: number;

before(async () => {
  [server, second, previous] = await Promise.all([
    startServer(), startProcess(), startProcess(new URL('../../stage-1/src/main.ts', import.meta.url).pathname),
  ]);
  port = server.port;
});
after(() => Promise.all([server.close(), second.close(), previous.close()]));
beforeEach(() => reset(port, fixture({ settlement_operator_ids: ['u_ada'] })));

const key = () => randomUUID();
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const TS_RE = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$/;
const exportFrom = async (p: number) => {
  const reply = await request(p, 'GET', '/_test/export');
  assert.equal(reply.status, 200);
  return reply.body;
};
const importInto = (p: number, body: unknown) => request(p, 'POST', '/_test/import', { json: body });
const as = (c: Client, p: number) => new Client(p, c.token);
const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString().replace('Z', '+00:00');

async function view(clients: Client[]) {
  return Promise.all(clients.map(async (c) => ({
    me: (await c.get('/me')).body,
    activity: (await c.get('/activity?limit=200')).body,
    requests: (await c.get('/requests?limit=200')).body,
    authorizations: (await c.get('/authorizations?limit=200')).body,
  })));
}

// Every kind of authorization: open, seeded open, partially captured and still open, captured
// after a partial capture, voided after a partial capture, expired by the clock (seeded an hour
// past its deadline, so stored open), and seeded expired.
async function populateHolds(p = port) {
  await reset(p, fixture({
    authorization_ttl_seconds: 3600,
    settlement_operator_ids: ['u_ada'],
    authorizations: [
      { id: 'a_seed_open', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 400, expires_at: inHours(2), note: 'seed' },
      { id: 'a_seed_exp', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 900, status: 'expired', expires_at: inHours(-2) },
      { id: 'a_seed_lapsed', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 300, expires_at: inHours(-1) },
    ],
  }));
  const [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(p, h)));
  const keys = { open: key(), partial: key(), cap1: key(), cap2: key(), voided: key(), vcap: key() };
  const auth = (k: string, amount: number, extra = {}) =>
    ada.post('/authorizations', { json: { to_handle: 'bob', amount, ...extra }, key: k });
  const open = (await auth(keys.open, 1000, { visibility: 'private', note: 'deposit' })).body;
  const partial = (await auth(keys.partial, 2000)).body;
  const cap1 = (await bob.post(`/authorizations/${partial.authorization_id}/capture`,
    { json: { amount: 500, final: false }, key: keys.cap1 })).body;
  const done = (await auth(key(), 800)).body;
  await bob.post(`/authorizations/${done.authorization_id}/capture`, { json: { amount: 300, final: false }, key: key() });
  const cap2 = (await bob.post(`/authorizations/${done.authorization_id}/capture`, { json: {}, key: keys.cap2 })).body;
  const voided = (await auth(keys.voided, 600)).body;
  await bob.post(`/authorizations/${voided.authorization_id}/capture`, { json: { amount: 100, final: false }, key: keys.vcap });
  await ada.post(`/authorizations/${voided.authorization_id}/void`);
  return { ada, bob, cy, keys, open, partial, cap1, cap2, voided, done };
}

describe('GET /_test/export, schema 2 (W8.1)', () => {
  it('carries the TTL, every authorization with its stored fields and each payment\'s authorization_id', async () => {
    const w = await populateHolds();
    const snapshot = await exportFrom(port);
    assert.equal(snapshot.format_version, 1);
    const s = snapshot.state;
    assert.equal(s.schema, 4, 'stage 4 exports schema 4, a superset of schema 2');
    assert.equal(s.authorization_ttl_seconds, 3600);
    assert.ok(!JSON.stringify(snapshot).includes(PASSWORD));
    const byId = new Map(s.authorizations.map((a: any) => [a.id, a]));
    assert.deepEqual([...byId.keys()], ['a_seed_open', 'a_seed_exp', 'a_seed_lapsed', w.open.authorization_id,
      w.partial.authorization_id, w.done.authorization_id, w.voided.authorization_id]);
    for (const a of s.authorizations) {
      assert.deepEqual(Object.keys(a).sort(), ['amount', 'base_captured_amount', 'capture_payment_ids', 'captured_amount',
        'closed_at', 'created_at', 'expires_at', 'from_user_id', 'id', 'note', 'payment_id', 'payment_ids', 'seq', 'status',
        'to_user_id', 'visibility']);
      // Schema 3 (D84): a seeded captured amount is the base; API captures are listed apart.
      assert.equal(a.base_captured_amount, 0);
      assert.deepEqual(a.capture_payment_ids, a.payment_ids);
      assert.match(a.created_at, TS_RE);
    }
    const lapsed: any = byId.get('a_seed_lapsed');
    assert.deepEqual([lapsed.status, lapsed.closed_at], ['open', null], 'clock expiry is stored as open, closed_at null');
    const seedExp: any = byId.get('a_seed_exp');
    assert.equal(seedExp.closed_at, seedExp.created_at);
    const done: any = byId.get(w.done.authorization_id);
    assert.deepEqual([done.status, done.captured_amount, done.closed_at, done.payment_ids.length],
      ['captured', 800, w.cap2.created_at, 2]);
    const voided: any = byId.get(w.voided.authorization_id);
    assert.deepEqual([voided.status, voided.captured_amount], ['voided', 100]);
    assert.match(voided.closed_at, TS_RE);
    const partial: any = byId.get(w.partial.authorization_id);
    assert.deepEqual([partial.status, partial.captured_amount, partial.closed_at, partial.payment_ids],
      ['open', 500, null, [w.cap1.payment_id]]);
    assert.equal((byId.get(w.open.authorization_id) as any).expires_at, w.open.expires_at);
    const captures = s.payments.filter((p: any) => p.authorization_id !== null);
    assert.equal(captures.length, 4);
    for (const p of s.payments) assert.ok('authorization_id' in p);
  });
});

describe('stage-2 round trip (W8.2)', () => {
  it('restores every authorization, hold, capture payment and key, here and in another process', async () => {
    const w = await populateHolds();
    const before = await view([w.ada, w.bob, w.cy]);
    assert.deepEqual(before[0].me, {
      ...before[0].me, total: 10_000 - 500 - 800 - 100, held: 1000 + 1500 + 400, available: 10_000 - 1400 - 2900,
    });
    const snapshot = await exportFrom(port);
    for (const target of [port, second.port]) {
      if (target === port) await reset(port, fixture());
      assert.equal((await importInto(target, snapshot)).status, 204);
      const clients = [w.ada, w.bob, w.cy].map((c) => as(c, target));
      assert.deepEqual(await view(clients), before);
      assert.deepEqual(await exportFrom(target), snapshot);
      const [ada, bob] = clients;
      // Replays of authorization and capture keys return the originals and move nothing.
      const replayOpen = await ada.post('/authorizations',
        { json: { to_handle: 'bob', amount: 1000, visibility: 'private', note: 'deposit' }, key: w.keys.open });
      assert.deepEqual([replayOpen.status, replayOpen.body], [200, w.open]);
      const replayCap = await bob.post(`/authorizations/${w.partial.authorization_id}/capture`,
        { json: { amount: 500, final: false }, key: w.keys.cap1 });
      assert.deepEqual([replayCap.status, replayCap.body], [200, w.cap1]);
      const replayFinal = await bob.post(`/authorizations/${w.done.authorization_id}/capture`, { json: {}, key: w.keys.cap2 });
      assert.deepEqual([replayFinal.status, replayFinal.body], [200, w.cap2]);
      assert.deepEqual(await view(clients), before);
      // The holds still work: capture the rest of the partial one, void the open one.
      const rest = await bob.post(`/authorizations/${w.partial.authorization_id}/capture`, { json: {}, key: key() });
      assert.equal(rest.status, 201);
      assert.equal(rest.body.amount, 1500);
      assert.equal((await ada.post(`/authorizations/${w.open.authorization_id}/void`)).status, 200);
      const me = (await ada.get('/me')).body;
      assert.deepEqual([me.total, me.held, me.available], [10_000 - 2900, 400, 10_000 - 2900 - 400]);
    }
  });

  it('an open authorization whose deadline passes after the import expires by the clock', async () => {
    await reset(port, fixture({ authorization_ttl_seconds: 2 }));
    const ada = await login(port, 'ada');
    const a = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 3000 }, key: key() })).body;
    const snapshot = await exportFrom(port);
    assert.equal((await importInto(second.port, snapshot)).status, 204);
    const there = as(ada, second.port);
    assert.equal((await there.get('/me')).body.held, 3000);
    await sleep(Date.parse(a.expires_at) - Date.now() + 50);
    const me = (await there.get('/me')).body;
    assert.deepEqual([me.total, me.available, me.held], [10_000, 10_000, 0]);
    const [item] = (await there.get('/authorizations')).body.authorizations;
    assert.equal(item.status, 'expired');
    expectError(await as(await login(second.port, 'bob'), second.port)
      .post(`/authorizations/${a.authorization_id}/capture`, { json: {}, key: key() }), 409, 'authorization_expired');
  });

  it('a payer who spent money after a hold\'s deadline exports and imports back', async () => {
    await reset(port, fixture({ authorization_ttl_seconds: 1 }));
    const cy = await login(port, 'cy');
    const a = (await cy.post('/authorizations', { json: { to_handle: 'bob', amount: 500 }, key: key() })).body;
    await sleep(Date.parse(a.expires_at) - Date.now() + 50);
    assert.equal((await cy.post('/payments', { json: { to_handle: 'ada', amount: 450 }, key: key() })).status, 201);
    const snapshot = await exportFrom(port);
    const stored = snapshot.state.authorizations[0];
    assert.deepEqual([stored.status, stored.amount], ['open', 500]);
    assert.equal((await importInto(second.port, snapshot)).status, 204);
    const me = (await as(cy, second.port).get('/me')).body;
    assert.deepEqual([me.total, me.available, me.held], [50, 50, 0]);
  });

  it('a fixture whose authorizations link to payments that do not exist round-trips (D62)', async () => {
    await reset(port, fixture({
      authorizations: [{ id: 'a_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 100, status: 'captured',
        payment_ids: ['p_ghost', 'p_other'], expires_at: inHours(-3) }],
      payments: [{ id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 5, authorization_id: 'a_elsewhere' }],
    }));
    const snapshot = await exportFrom(port);
    assert.equal((await importInto(second.port, snapshot)).status, 204);
    assert.deepEqual(await exportFrom(second.port), snapshot);
  });
});

describe('upgrade from a stage-1 export (W8.3)', () => {
  it('imports an unchanged stage-1 export and keeps every promise of stage 1', async () => {
    const p = previous.port;
    await reset(p, fixture({ settlement_operator_ids: ['u_ada'] }));
    const [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(p, h)));
    const keys = { pay: key(), ask: key(), pending: key(), payReq: key(), split: key(), settle: key(), failed: key(), lost: key() };
    const payBody = { to_handle: 'bob', amount: 700, note: 'café 😀', visibility: 'private' };
    const payment = (await ada.post('/payments', { json: payBody, key: keys.pay })).body;
    assert.ok(!('authorization_id' in payment), 'this really is a stage-1 build');
    const ask = (await bob.post('/requests', { json: { payer_handle: 'ada', amount: 300 }, key: keys.ask })).body;
    const paid = (await ada.post(`/requests/${ask.request_id}/pay`, { json: {}, key: keys.payReq })).body;
    const pending = (await cy.post('/requests', { json: { payer_handle: 'bob', amount: 120, note: 'lunch' }, key: keys.pending })).body;
    const split = (await cy.post('/splits', { json: { amount: 1001, participant_handles: ['cy', 'ada', 'bob'] }, key: keys.split })).body;
    const settlement = (await ada.post('/settlements', {
      json: { transfers: [{ from_handle: 'bob', to_handle: 'cy', amount: 50 }] }, key: keys.settle,
    })).body;
    expectError(await cy.post('/payments', { json: { to_handle: 'ada', amount: 999_999 }, key: keys.failed }), 409, 'insufficient_funds');
    const stageOneViews = await Promise.all([ada, bob, cy].map(async (c) => ({
      me: (await c.get('/me')).body,
      activity: (await c.get('/activity?limit=200')).body,
      requests: (await c.get('/requests?limit=200')).body,
    })));
    const snapshot = await exportFrom(p);
    assert.equal(snapshot.state.schema, 1);

    assert.equal((await importInto(port, snapshot)).status, 204);
    const [a2, b2, c2] = [ada, bob, cy].map((c) => as(c, port));
    for (const [i, c] of [a2, b2, c2].entries()) {
      const was = stageOneViews[i];
      const me = (await c.get('/me')).body;
      assert.deepEqual(me, { ...was.me, total: was.me.balance, available: was.me.balance, held: 0 });
      assert.deepEqual(Object.keys(me), ['user_id', 'display_name', 'handle', 'balance', 'total', 'available', 'held',
        'currency', 'minor_units']);
      const feed = (await c.get('/activity?limit=200')).body;
      assert.deepEqual(feed, {
        ...was.activity,
        payments: was.activity.payments.map((x: any) => {
          const { created_at: createdAt, ...rest } = x;
          return { ...rest, authorization_id: null, refund_of: null, created_at: createdAt };
        }),
      });
      assert.deepEqual((await c.get('/requests?limit=200')).body, was.requests);
      assert.deepEqual((await c.get('/authorizations')).body, { authorizations: [], has_more: false });
    }
    const imported = await exportFrom(port);
    assert.equal(imported.state.schema, 4);
    assert.equal(imported.state.authorization_ttl_seconds, 600);
    // Through a schema-2 export and import, the stage-1 replay bodies stay verbatim.
    assert.equal((await importInto(second.port, imported)).status, 204);
    const onward = await as(ada, second.port).post('/payments', { json: payBody, key: keys.pay });
    assert.deepEqual([onward.status, onward.body], [200, payment]);
    assert.deepEqual(await exportFrom(second.port), imported);

    // Replays return the stored stage-1 bodies unchanged (D54); failed keys are free.
    const replay = await a2.post('/payments', { json: payBody, key: keys.pay });
    assert.deepEqual([replay.status, replay.body], [200, payment]);
    assert.ok(!('authorization_id' in replay.body));
    const replayPaid = await a2.post(`/requests/${ask.request_id}/pay`, { json: {}, key: keys.payReq });
    assert.deepEqual([replayPaid.status, replayPaid.body], [200, paid]);
    const replaySplit = await c2.post('/splits', { json: { amount: 1001, participant_handles: ['cy', 'ada', 'bob'] }, key: keys.split });
    assert.deepEqual([replaySplit.status, replaySplit.body], [200, split]);
    const replaySettle = await a2.post('/settlements', {
      json: { transfers: [{ from_handle: 'bob', to_handle: 'cy', amount: 50 }] }, key: keys.settle,
    });
    assert.deepEqual([replaySettle.status, replaySettle.body], [200, settlement]);
    expectError(await a2.post('/payments', { json: { ...payBody, amount: 701 }, key: keys.pay }), 409, 'idempotency_key_reuse');
    assert.equal((await c2.post('/payments', { json: { to_handle: 'ada', amount: 1 }, key: keys.failed })).status, 201);

    // Logins work; the pending request is payable; new authorizations work; ids and timestamps move on.
    const fresh = await login(port, 'bob', PASSWORD);
    const payPending = await fresh.post(`/requests/${pending.request_id}/pay`, { json: {}, key: key() });
    assert.equal(payPending.status, 201);
    assert.equal(payPending.body.authorization_id, null);
    const hold = await a2.post('/authorizations', { json: { to_handle: 'cy', amount: 250 }, key: key() });
    assert.equal(hold.status, 201);
    const latest = snapshot.state.last_ts;
    assert.ok(hold.body.created_at >= latest && payPending.body.created_at >= latest);
    const allIds = new Set([...snapshot.state.payments.map((x: any) => x.id), ...snapshot.state.requests.map((x: any) => x.id)]);
    assert.ok(!allIds.has(payPending.body.payment_id));
    const me = (await a2.get('/me')).body;
    assert.deepEqual([me.held, me.available], [250, me.total - 250]);
    const feed = (await a2.get('/activity')).body.payments;
    assert.equal(feed[0].payment_id, payPending.body.payment_id, 'newest first after the import');
  });

  it('refuses invalid schema-2 states and leaves the destination unchanged (W8.4)', async () => {
    const w = await populateHolds();
    const snapshot = await exportFrom(port);
    const s = snapshot.state;
    const [a0, ...rest] = s.authorizations;
    const withAuth = (patch: Record<string, unknown>) => ({ ...snapshot, state: { ...s, authorizations: [{ ...a0, ...patch }, ...rest] } });
    const bad: [string, unknown][] = [
      ['schema 5', { ...snapshot, state: { ...s, schema: 5 } }],
      ['schema "2"', { ...snapshot, state: { ...s, schema: '2' } }],
      ['no TTL', { ...snapshot, state: { ...s, authorization_ttl_seconds: undefined } }],
      ['TTL 0', { ...snapshot, state: { ...s, authorization_ttl_seconds: 0 } }],
      ['no authorizations', { ...snapshot, state: { ...s, authorizations: undefined } }],
      ['payment without authorization_id', { ...snapshot, state: { ...s, payments: s.payments.map((p: any, i: number) =>
        (i === 0 ? { ...p, authorization_id: undefined } : p)) } }],
      ['payment authorization_id 5', { ...snapshot, state: { ...s, payments: s.payments.map((p: any, i: number) =>
        (i === 0 ? { ...p, authorization_id: 5 } : p)) } }],
      ['dangling payer', withAuth({ from_user_id: 'u_ghost' })],
      ['dangling receiver', withAuth({ to_user_id: 'u_ghost' })],
      ['self', withAuth({ to_user_id: a0.from_user_id })],
      ['unknown status', withAuth({ status: 'pending' })],
      ['captured above amount', withAuth({ captured_amount: a0.amount + 1 })],
      ['open fully captured', withAuth({ captured_amount: a0.amount })],
      ['duplicate id', { ...snapshot, state: { ...s, authorizations: [...s.authorizations, a0] } }],
      ['expires_at not RFC 3339', withAuth({ expires_at: '2099-02-30T00:00:00Z' })],
      ['payment_ids a string', withAuth({ payment_ids: 'p_1' })],
      ['payment_ids of numbers', withAuth({ payment_ids: [1] })],
      ['payment_id 5', withAuth({ payment_id: 5 })],
      ['created_at missing', withAuth({ created_at: undefined })],
      ['closed_at bad', withAuth({ closed_at: 'later' })],
      ['seq missing', withAuth({ seq: undefined })],
      ['unexpired remainders above the total', withAuth({ amount: 1_000_000_000 })],
    ];
    const before = await view([w.ada, w.bob, w.cy]);
    for (const [label, body] of bad) {
      const reply = await importInto(port, body);
      assert.ok(reply.status === 422 && reply.body?.error?.code === 'validation_failed', `${label}: ${reply.status} ${reply.text}`);
    }
    assert.deepEqual(await view([w.ada, w.bob, w.cy]), before);
    const lapsed = withAuth({ amount: 1_000_000_000, expires_at: inHours(-1) });
    assert.equal((await importInto(port, lapsed)).status, 204, 'a lapsed hold holds nothing, whatever its amount');
    // The import's time is its clock (D49): an imported state whose clock ran ahead judges expiry by it.
    const ahead = { ...snapshot, state: { ...s, last_ts: '2099-01-01T00:00:00.000+00:00',
      authorizations: [{ ...a0, amount: 1_000_000_000, expires_at: '2050-01-01T00:00:00Z' }, ...rest] } };
    assert.equal((await importInto(port, ahead)).status, 204, 'expired by the imported clock');
    const me = (await w.ada.get('/me')).body;
    assert.deepEqual([me.held, me.available], [0, me.total], 'at the imported clock every hold has expired');
  });
});

// The service clock (D49) across an import whose clock ran ahead of the wall clock.
describe('the clock after an import that ran ahead (D49)', () => {
  const AHEAD = '2099-01-01T00:00:00.000+00:00';

  it('a reset starts at its own time, not the imported clock (I25, W7.8)', async () => {
    const snapshot = await exportFrom(port);
    assert.equal((await importInto(port, { ...snapshot, state: { ...snapshot.state, last_ts: AHEAD } })).status, 204);
    const before = await login(port, 'ada');
    const early = await before.post('/payments', { json: { to_handle: 'bob', amount: 1 }, key: key() });
    assert.ok(early.body.created_at >= AHEAD, 'the imported clock is in force before the reset');

    await reset(port, fixture({
      authorizations: [{ id: 'a_two_hours', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 400, expires_at: inHours(2) }],
    }));
    const ada = await login(port, 'ada');
    const me = (await ada.get('/me')).body;
    assert.deepEqual([me.total, me.held, me.available], [10_000, 400, 9_600], 'the seeded open hold counts right after the reset');
    const [hold] = (await ada.get('/authorizations')).body.authorizations;
    assert.deepEqual([hold.authorization_id, hold.status], ['a_two_hours', 'open']);
    assert.ok(hold.created_at < '2099', `seeded at the reset's time: ${hold.created_at}`);
    const paid = await ada.post('/payments', { json: { to_handle: 'bob', amount: 1 }, key: key() });
    assert.equal(paid.status, 201);
    assert.ok(paid.body.created_at < '2099', `a new payment after the reset: ${paid.body.created_at}`);
    assert.ok((await exportFrom(port)).state.last_ts < '2099');
  });

  it('a hold whose deadline is exactly the imported clock has expired; one a millisecond later is open', async () => {
    await reset(port, fixture({
      authorizations: [
        { id: 'a_at', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 300, expires_at: inHours(2) },
        { id: 'a_after', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 200, expires_at: inHours(2) },
      ],
    }));
    const snapshot = await exportFrom(port);
    const deadline = { a_at: '2099-01-01T00:00:00Z', a_after: '2099-01-01T00:00:00.001Z' } as Record<string, string>;
    // a_at is raised to 9900: with a_after's 200 that exceeds ada's 10000, so the import is
    // accepted only because a_at has expired at the import's clock.
    const amount = { a_at: 9_900, a_after: 200 } as Record<string, number>;
    const state = {
      ...snapshot.state,
      last_ts: AHEAD,
      authorizations: snapshot.state.authorizations.map((a: any) => ({ ...a, expires_at: deadline[a.id], amount: amount[a.id] })),
    };
    const imported = await importInto(port, { ...snapshot, state });
    assert.equal(imported.status, 204, imported.text);
    const [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(port, h)));

    const me = (await ada.get('/me')).body;
    assert.deepEqual([me.held, me.available], [200, me.total - 200], 'only the hold a millisecond past the clock holds');
    const status = Object.fromEntries((await ada.get('/authorizations')).body.authorizations
      .map((a: any) => [a.authorization_id, [a.status, a.expires_at]]));
    assert.deepEqual(status, { a_at: ['expired', deadline.a_at], a_after: ['open', deadline.a_after] });
    expectError(await cy.post('/authorizations/a_at/capture', { json: { amount: 1, final: false }, key: key() }), 409,
      'authorization_expired');
    assert.deepEqual((await ada.get('/me')).body, me, 'the refused capture changed nothing');
    const captured = await bob.post('/authorizations/a_after/capture', { json: { amount: 50, final: false }, key: key() });
    assert.equal(captured.status, 201, captured.text);
    // Checked at the imported clock, before the deadline; recorded at the next issued timestamp,
    // a millisecond later (stage 3, D67).
    assert.equal(captured.body.created_at, '2099-01-01T00:00:00.001+00:00', 'issued strictly after the imported clock');
    // The capture's issued timestamp is a_after's deadline, so the clock now stands at it and the
    // rest of the hold has expired.
    const after = (await ada.get('/me')).body;
    assert.deepEqual([after.total, after.held], [me.total - 50, 0]);
    const [aAfter] = (await ada.get('/authorizations')).body.authorizations.filter((a: any) => a.authorization_id === 'a_after');
    assert.deepEqual([aAfter.status, aAfter.captured_amount, aAfter.closed_at], ['expired', 50, deadline.a_after]);
  });
});

describe('a stage-1 fixture shape still resets (W8.3)', () => {
  it('needs neither the TTL nor authorizations', async () => {
    await reset(port, { currency: 'EUR', minor_units: 2, users: [user('ada', 1)] });
    assert.equal((await exportFrom(port)).state.authorization_ttl_seconds, 600);
  });
});
