// W17: export schema 3, round trips, the upgrade from the frozen stage-1 and stage-2 builds,
// and invalid schema-3 states.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, describe, it } from 'node:test';
import { Client, expectError, fixture, login, request, reset, startProcess, startServer, type Server } from './helpers.ts';

let server: Server;
let second: Server; // another stage-3 process
let stageOne: Server; // the frozen stage-1 build
let stageTwo: Server; // the frozen stage-2 build
let port: number;

before(async () => {
  [server, second, stageOne, stageTwo] = await Promise.all([
    startServer(), startProcess(),
    startProcess(new URL('../../stage-1/src/main.ts', import.meta.url).pathname),
    startProcess(new URL('../../stage-2/src/main.ts', import.meta.url).pathname),
  ]);
  port = server.port;
});
after(() => Promise.all([server.close(), second.close(), stageOne.close(), stageTwo.close()]));

const key = () => randomUUID();
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString().replace('Z', '+00:00');
const microBefore = (ts: string) => new Date(Date.parse(ts) - 1).toISOString().replace('Z', '999Z');
const exportFrom = async (p: number) => {
  const reply = await request(p, 'GET', '/_test/export');
  assert.equal(reply.status, 200);
  return reply.body;
};
const importInto = (p: number, body: unknown) => request(p, 'POST', '/_test/import', { json: body });
const as = (c: Client, p: number) => new Client(p, c.token);
const correct = (c: Client, id: string, json: unknown, k = key()) => c.post(`/payments/${id}/corrections`, { json, key: k });

// A stage-3 history: seeded past payments and holds, payments, a request, a settlement, holds
// and captures, corrections and statements with snapshots.
async function populate() {
  await reset(port, fixture({
    settlement_operator_ids: ['u_ada'],
    payments: [{ id: 'p_seed', from_user_id: 'u_bob', to_user_id: 'u_ada', amount: 300, created_at: '2020-01-01T00:00:00.5+02:00' }],
    authorizations: [
      { id: 'a_seed', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 200, expires_at: inHours(2), created_at: '2020-02-01T00:00:00Z' },
      { id: 'a_seed_voided', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 900, status: 'voided', expires_at: inHours(2), created_at: '2020-02-01T00:00:00Z' },
    ],
  }));
  const [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(port, h)));
  const paid = (await ada.post('/payments', { json: { to_handle: 'bob', amount: 1_000 }, key: key() })).body;
  const ask = (await bob.post('/requests', { json: { payer_handle: 'ada', amount: 40 }, key: key() })).body;
  await ada.post(`/requests/${ask.request_id}/pay`, { json: {}, key: key() });
  await ada.post('/settlements', { json: { transfers: [{ from_handle: 'bob', to_handle: 'cy', amount: 25 }] }, key: key() });
  const hold = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 500 }, key: key() })).body;
  await bob.post(`/authorizations/${hold.authorization_id}/capture`, { json: { amount: 120, final: false }, key: key() });
  const snapBefore = (await ada.get('/statement?limit=2')).body;
  const fixKey = key();
  const fixBody = { expected_revision: 1, amount: 600, effective_at: '2020-06-01T00:00:00Z', reason: 'backdated' };
  const fix = (await correct(ada, paid.payment_id, fixBody, fixKey)).body;
  const snapAfter = (await ada.get(`/statement?known_at=${encodeURIComponent(fix.recorded_at)}&limit=3`)).body;
  return { ada, bob, cy, paid, hold, fix, fixKey, fixBody, snapBefore, snapAfter };
}

// Everything a reader can see of the history, for comparing two services.
async function history(clients: Client[], w: Awaited<ReturnType<typeof populate>>) {
  return Promise.all(clients.map(async (c) => ({
    me: (await c.get('/me')).body,
    early: (await c.get('/me?as_of=2019-01-01T00:00:00Z')).body,
    mid: (await c.get('/me?as_of=2020-03-01T00:00:00Z')).body,
    known: (await c.get(`/me?known_at=${encodeURIComponent(microBefore(w.fix.recorded_at))}`)).body,
    statement: (({ snapshot, ...rest }) => rest)((await c.get('/statement?limit=200')).body),
    authorizations: (await c.get('/authorizations?limit=200')).body,
    revisions: (await c.get(`/payments/${w.paid.payment_id}/revisions`)).body,
  })));
}

describe('export schema 3 (W17.1)', () => {
  it('carries revisions, opening balances, snapshots, seeded_closed and correction keys', async () => {
    const w = await populate();
    const { state: s } = await exportFrom(port);
    assert.equal(s.schema, 3);
    const users = Object.fromEntries(s.users.map((u: any) => [u.id, u]));
    assert.deepEqual([users.u_ada.opening_balance, users.u_bob.opening_balance, users.u_cy.opening_balance], [9_700, 2_800, 500]);
    const paid = s.payments.find((p: any) => p.id === w.paid.payment_id);
    assert.deepEqual(paid.revisions.map(({ seq, ...r }: any) => r), [
      { revision: 1, amount: 1_000, effective_at: w.paid.created_at, recorded_at: w.paid.created_at, reason: '' },
      { revision: 2, amount: 600, effective_at: '2020-06-01T00:00:00Z', recorded_at: w.fix.recorded_at, reason: 'backdated' },
    ]);
    assert.equal(paid.revisions[0].seq, paid.seq);
    assert.ok(paid.revisions[1].seq > paid.seq);
    for (const p of s.payments) assert.equal(p.revisions[0].amount, p.amount);
    assert.deepEqual(s.snapshots.map((x: any) => x.token).sort(), [w.snapBefore.snapshot, w.snapAfter.snapshot].sort());
    const after = s.snapshots.find((x: any) => x.token === w.snapAfter.snapshot);
    assert.deepEqual([after.owner_id, after.from, after.known_at], ['u_ada', null, w.fix.recorded_at]);
    assert.ok(after.cutoff <= s.seq && Date.parse(after.to) > Date.parse(w.fix.recorded_at), 'the defaulted to');
    assert.deepEqual(s.authorizations.map((a: any) => [a.id, a.seeded_closed]),
      [['a_seed', false], ['a_seed_voided', true], [w.hold.authorization_id, false]]);
    assert.ok(s.idempotency.some((r: any) => r.path === `/payments/${w.paid.payment_id}/corrections` && r.key === w.fixKey));
  });
});

describe('schema-3 round trip (W17.2)', () => {
  it('restores the history, the snapshots and the correction replays, here and in another process', async () => {
    const w = await populate();
    const clients = [w.ada, w.bob, w.cy];
    const before = await history(clients, w);
    // The seeded voided hold, created before the reset, holds nothing at any instant.
    assert.equal(before[0].mid.held, 200);
    const snapshot = await exportFrom(port);
    for (const target of [port, second.port]) {
      if (target === port) await reset(port, fixture());
      assert.equal((await importInto(target, snapshot)).status, 204);
      assert.deepEqual(await exportFrom(target), snapshot);
      const there = clients.map((c) => as(c, target));
      assert.deepEqual(await history(there, w), before);
      const [ada] = there;
      assert.deepEqual((await ada.get(`/statement?snapshot=${w.snapBefore.snapshot}&limit=2`)).body, w.snapBefore);
      assert.deepEqual((await ada.get(`/statement?snapshot=${w.snapAfter.snapshot}&limit=3`)).body, w.snapAfter);
      const replay = await correct(ada, w.paid.payment_id, w.fixBody, w.fixKey);
      assert.deepEqual([replay.status, replay.body], [200, w.fix]);
      expectError(await as(w.bob, target).get(`/statement?snapshot=${w.snapBefore.snapshot}`), 404, 'not_found');
      // The history goes on: a new correction is recorded after the imported ones.
      const next = await correct(ada, w.paid.payment_id, { ...w.fixBody, expected_revision: 2, amount: 650 });
      assert.equal(next.status, 201, next.text);
      assert.ok(next.body.recorded_at > w.fix.recorded_at);
    }
  });
});

describe('the clock after a schema-3 import', () => {
  it('starts after every imported recorded_at, so a payment\'s recorded times still increase', async () => {
    const w = await populate();
    const exported = await exportFrom(port);
    const LATER = '2099-01-01T00:00:00.000+00:00';
    const state = {
      ...exported.state,
      payments: exported.state.payments.map((p: any) => (p.id !== w.paid.payment_id ? p
        : { ...p, revisions: [p.revisions[0], { ...p.revisions[1], recorded_at: LATER }] })),
    };
    assert.ok(state.last_ts < LATER);
    assert.equal((await importInto(second.port, { ...exported, state })).status, 204);
    const next = await correct(as(w.ada, second.port), w.paid.payment_id, { ...w.fixBody, expected_revision: 2, amount: 610 });
    assert.equal(next.status, 201, next.text);
    assert.ok(next.body.recorded_at > LATER, next.body.recorded_at);
  });
});

describe('upgrade from the frozen builds (W17.3)', () => {
  it('lifts a stage-2 export: revision 1, openings, hold history and closed_at, verbatim replays', async () => {
    const p = stageTwo.port;
    await reset(p, fixture({ settlement_operator_ids: ['u_ada'] }));
    const [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(p, h)));
    const payKey = key();
    const payBody = { to_handle: 'bob', amount: 700 };
    const payment = (await ada.post('/payments', { json: payBody, key: payKey })).body;
    const pending = (await cy.post('/requests', { json: { payer_handle: 'bob', amount: 120 }, key: key() })).body;
    const settled = (await ada.post('/settlements', { json: { transfers: [{ from_handle: 'bob', to_handle: 'cy', amount: 50 }] }, key: key() })).body;
    const holdKey = key();
    const hold = (await ada.post('/authorizations', { json: { to_handle: 'cy', amount: 400 }, key: holdKey })).body;
    assert.equal('closed_at' in hold, false, 'this really is a stage-2 build');
    // Stage 2's timestamps may repeat within a millisecond; keep these events apart.
    await sleep(5);
    const capKey = key();
    const capture = (await cy.post(`/authorizations/${hold.authorization_id}/capture`, { json: { amount: 100, final: false }, key: capKey })).body;
    await sleep(5);
    const voidable = (await ada.post('/authorizations', { json: { to_handle: 'cy', amount: 300 }, key: key() })).body;
    await sleep(5);
    assert.equal((await ada.post(`/authorizations/${voidable.authorization_id}/void`)).status, 200);
    const exported = await exportFrom(p);
    assert.equal(exported.state.schema, 2);
    const voided = exported.state.authorizations.find((a: any) => a.id === voidable.authorization_id);
    assert.match(voided.closed_at, /^\d{4}-/);

    assert.equal((await importInto(port, exported)).status, 204);
    const [a3, b3, c3] = [ada, bob, cy].map((c) => as(c, port));
    const me = (await a3.get('/me')).body;
    assert.deepEqual([me.total, me.held], [10_000 - 700 - 100, 300]);
    assert.deepEqual((await a3.get('/me?as_of=2000-01-01T00:00:00Z')).body.total, 10_000, 'the opening balance');
    assert.deepEqual((await b3.get('/me?as_of=2000-01-01T00:00:00Z')).body.total, 2_500);
    for (const c of [a3, b3, c3]) assert.deepEqual((await c.get(`/me?as_of=${encodeURIComponent(exported.state.last_ts)}`)).body.total, (await c.get('/me')).body.total);
    assert.deepEqual((await a3.get(`/payments/${payment.payment_id}/revisions`)).body.revisions, [{
      payment_id: payment.payment_id, revision: 1, amount: 700, effective_at: payment.created_at, recorded_at: payment.created_at, reason: '',
    }]);
    // Hold history: 400 from its creation, 300 after the capture, plus the voided one until its void.
    assert.equal((await a3.get(`/me?as_of=${encodeURIComponent(microBefore(hold.created_at))}`)).body.held, 0);
    assert.equal((await a3.get(`/me?as_of=${encodeURIComponent(hold.created_at)}`)).body.held, 400);
    assert.equal((await a3.get(`/me?as_of=${encodeURIComponent(capture.created_at)}`)).body.held, 300);
    assert.equal((await a3.get(`/me?as_of=${encodeURIComponent(voidable.created_at)}`)).body.held, 600);
    assert.equal((await a3.get(`/me?as_of=${encodeURIComponent(microBefore(voided.closed_at))}`)).body.held, 600);
    assert.equal((await a3.get(`/me?as_of=${encodeURIComponent(voided.closed_at)}`)).body.held, 300);
    const listed = Object.fromEntries((await a3.get('/authorizations')).body.authorizations.map((a: any) => [a.authorization_id, a.closed_at]));
    assert.deepEqual(listed, { [hold.authorization_id]: null, [voidable.authorization_id]: voided.closed_at });
    // Stored stage-2 bodies replay verbatim, without closed_at.
    const replayHold = await a3.post('/authorizations', { json: { to_handle: 'cy', amount: 400 }, key: holdKey });
    assert.deepEqual([replayHold.status, replayHold.body], [200, hold]);
    const replayCap = await c3.post(`/authorizations/${hold.authorization_id}/capture`, { json: { amount: 100, final: false }, key: capKey });
    assert.deepEqual([replayCap.status, replayCap.body], [200, capture]);
    const replayPay = await a3.post('/payments', { json: payBody, key: payKey });
    assert.deepEqual([replayPay.status, replayPay.body], [200, payment]);
    // Logins, the pending request, a correction of an imported payment; captures and members stay fixed.
    const freshBob = await login(port, 'bob');
    assert.equal((await freshBob.post(`/requests/${pending.request_id}/pay`, { json: {}, key: key() })).status, 201);
    const fixed = await correct(a3, payment.payment_id, { expected_revision: 1, amount: 650, effective_at: payment.created_at, reason: 'fix' });
    assert.equal(fixed.status, 201, fixed.text);
    expectError(await correct(a3, capture.payment_id, { expected_revision: 1, amount: 1, effective_at: capture.created_at, reason: 'x' }), 422, 'linked_payment_immutable');
    expectError(await correct(b3, settled.payments[0].payment_id, { expected_revision: 1, amount: 1, effective_at: settled.committed_at, reason: 'x' }), 422, 'linked_payment_immutable');
  });

  it('lifts a stage-1 export: revision 1 at created_at and openings from the balances', async () => {
    const p = stageOne.port;
    await reset(p, fixture());
    const [ada, bob] = await Promise.all(['ada', 'bob'].map((h) => login(p, h)));
    const first = (await ada.post('/payments', { json: { to_handle: 'bob', amount: 300 }, key: key() })).body;
    await sleep(5); // stage 1 may give two payments one millisecond; the statement would order them by id
    const back = (await bob.post('/payments', { json: { to_handle: 'ada', amount: 50 }, key: key() })).body;
    const exported = await exportFrom(p);
    assert.equal(exported.state.schema, 1);
    assert.equal((await importInto(port, exported)).status, 204);
    const a3 = as(ada, port);
    assert.equal((await a3.get('/me?as_of=1999-01-01T00:00:00Z')).body.total, 10_000);
    assert.equal((await a3.get(`/me?as_of=${encodeURIComponent(first.created_at)}`)).body.total, 9_700);
    const statement = (await a3.get('/statement')).body;
    assert.deepEqual(statement.entries.map((e: any) => [e.payment.payment_id, e.delta, e.balance_after, e.revision]),
      [[first.payment_id, -300, 9_700, 1], [back.payment_id, 50, 9_750, 1]]);
    const fixed = await correct(a3, first.payment_id, { expected_revision: 1, amount: 200, effective_at: first.created_at, reason: 'less' });
    assert.equal(fixed.status, 201, fixed.text);
    assert.equal((await a3.get('/me')).body.total, 9_850);
  });
});

describe('invalid schema-3 states (W17.4)', () => {
  it('are 422 and change nothing', async () => {
    const w = await populate();
    const exported = await exportFrom(port);
    const s = exported.state;
    const i = s.payments.findIndex((p: any) => p.id === w.paid.payment_id);
    const withPayment = (patch: (p: any) => any) => ({ ...exported, state: { ...s, payments: s.payments.map((p: any, j: number) => (j === i ? patch(p) : p)) } });
    const [r1, r2] = s.payments[i].revisions;
    const users = (patch: (u: any) => any) => ({ ...exported, state: { ...s, users: s.users.map((u: any) => (u.id === 'u_ada' ? patch(u) : u)) } });
    const snaps = (list: any[]) => ({ ...exported, state: { ...s, snapshots: list } });
    const bad: [string, unknown][] = [
      ['schema 4', { ...exported, state: { ...s, schema: 4 } }],
      ['revision gap', withPayment((p) => ({ ...p, revisions: [r1, { ...r2, revision: 3 }] }))],
      ['no revisions', withPayment((p) => ({ ...p, revisions: [] }))],
      ['revisions missing', withPayment(({ revisions, ...p }) => p)],
      ['revision 1 amount', withPayment((p) => ({ ...p, revisions: [{ ...r1, amount: 999 }, r2] }))],
      ['revision 1 time', withPayment((p) => ({ ...p, revisions: [{ ...r1, effective_at: '2020-01-01T00:00:00Z' }, r2] }))],
      ['revision 1 reason', withPayment((p) => ({ ...p, revisions: [{ ...r1, reason: 'x' }, r2] }))],
      ['decreasing recorded_at', withPayment((p) => ({ ...p, revisions: [r1, { ...r2, recorded_at: microBefore(r1.recorded_at) }] }))],
      ['equal recorded_at', withPayment((p) => ({ ...p, revisions: [r1, { ...r2, recorded_at: r1.recorded_at }] }))],
      ['empty reason', withPayment((p) => ({ ...p, revisions: [r1, { ...r2, reason: '' }] }))],
      ['amount above the limit', withPayment((p) => ({ ...p, revisions: [r1, { ...r2, amount: 1_000_000_001 }] }))],
      ['effective_at not an instant', withPayment((p) => ({ ...p, revisions: [r1, { ...r2, effective_at: '2020-06-01' }] }))],
      ['revision seq', withPayment((p) => ({ ...p, revisions: [r1, { ...r2, seq: -1 }] }))],
      ['opening does not add up', users((u) => ({ ...u, opening_balance: u.opening_balance + 1 }))],
      ['opening missing', users(({ opening_balance, ...u }) => u)],
      ['snapshot owner unknown', snaps([{ ...s.snapshots[0], owner_id: 'u_ghost' }])],
      ['snapshot token repeated', snaps([s.snapshots[0], { ...s.snapshots[1], token: s.snapshots[0].token }])],
      ['snapshot cutoff beyond seq', snaps([{ ...s.snapshots[0], cutoff: s.seq + 1 }])],
      ['snapshot to not an instant', snaps([{ ...s.snapshots[0], to: null }])],
      ['snapshots missing', { ...exported, state: { ...s, snapshots: undefined } }],
      ['seeded_closed not a boolean', { ...exported, state: { ...s, authorizations: s.authorizations.map((a: any) => ({ ...a, seeded_closed: 'yes' })) } }],
    ];
    for (const [name, body] of bad) {
      const reply = await importInto(port, body);
      assert.ok(reply.status === 422 && reply.body?.error?.code === 'validation_failed', `${name}: ${reply.status} ${reply.text.slice(0, 200)}`);
    }
    assert.deepEqual(await exportFrom(port), exported);
  });
});
