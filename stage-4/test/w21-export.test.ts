// W21: export schema 4, round trips with refunds and batches, the upgrade from the frozen
// stage-1, stage-2 and stage-3 builds (snapshots keep their payment form, D106), and invalid
// schema-4 states.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, describe, it } from 'node:test';
import { Client, expectError, fixture, login, request, reset, startProcess, startServer, type Server } from './helpers.ts';

let server: Server;
let second: Server; // another stage-4 process
let stageOne: Server; // the frozen builds
let stageTwo: Server;
let stageThree: Server;
let port: number;

before(async () => {
  [server, second, stageOne, stageTwo, stageThree] = await Promise.all([
    startServer(), startProcess(),
    startProcess(new URL('../../stage-1/src/main.ts', import.meta.url).pathname),
    startProcess(new URL('../../stage-2/src/main.ts', import.meta.url).pathname),
    startProcess(new URL('../../stage-3/src/main.ts', import.meta.url).pathname),
  ]);
  port = server.port;
});
after(() => Promise.all([server, second, stageOne, stageTwo, stageThree].map((s) => s.close())));

const key = () => randomUUID();
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const later = (ts: string) => new Date(Date.parse(ts) + 1).toISOString().replace('Z', '+00:00');
const exportFrom = async (p: number) => {
  const reply = await request(p, 'GET', '/_test/export');
  assert.equal(reply.status, 200);
  return reply.body;
};
const importInto = (p: number, body: unknown) => request(p, 'POST', '/_test/import', { json: body });
const as = (c: Client, p: number) => new Client(p, c.token);
const post = async (c: Client, path: string, json: unknown, k = key()) => {
  const reply = await c.post(path, { json, key: k });
  assert.equal(reply.status, 201, `${path}: ${reply.text}`);
  return reply.body;
};
const item = (id: string, expected: number, amount: number, effectiveAt: string) => ({
  payment_id: id, expected_revision: expected, amount, effective_at: effectiveAt, reason: 'fix',
});

// A stage-4 history: a seeded payment, payments, a settlement, a hold and a nonfinal capture,
// refunds of a payment, the capture and a settlement member, a correction, a batch over the
// whole settlement and the seeded payment, and statements before and after.
async function populate() {
  await reset(port, fixture({
    settlement_operator_ids: ['u_ada'],
    payments: [{ id: 'p_seed', from_user_id: 'u_bob', to_user_id: 'u_ada', amount: 300, created_at: '2020-01-01T00:00:00Z' }],
  }));
  const [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(port, h)));
  const paid = await post(ada, '/payments', { to_handle: 'bob', amount: 1_000, note: 'rent' });
  const settled = await post(ada, '/settlements', { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 50 }, { from_handle: 'bob', to_handle: 'cy', amount: 20 }] });
  const [m1, m2] = settled.payments;
  const hold = await post(ada, '/authorizations', { to_handle: 'bob', amount: 500 });
  const capture = await post(bob, `/authorizations/${hold.authorization_id}/capture`, { amount: 120, final: false });
  const snapBefore = (await bob.get('/statement?limit=2')).body;
  const refundKey = key();
  const refund = await post(bob, `/payments/${paid.payment_id}/refunds`, { amount: 200 }, refundKey);
  const capRefund = await post(bob, `/payments/${capture.payment_id}/refunds`, { amount: 20 });
  const memberRefund = await post(cy, `/payments/${m2.payment_id}/refunds`, { amount: 5 });
  const late = await post(ada, '/payments', { to_handle: 'bob', amount: 10 });
  const late2 = await post(ada, '/payments', { to_handle: 'bob', amount: 300 });
  const fix = await post(ada, `/payments/${paid.payment_id}/corrections`, { expected_revision: 1, amount: 900, effective_at: paid.created_at, reason: 'less' });
  const batchKey = key();
  const batchBody = { corrections: [
    item(m1.payment_id, 1, 40, settled.committed_at), item(m2.payment_id, 1, 15, settled.committed_at),
    item('p_seed', 1, 250, '2020-01-01T00:00:00Z'),
  ] };
  const batch = await post(ada, '/correction-batches', batchBody, batchKey);
  const snapAfter = (await bob.get('/statement?limit=3')).body;
  return { ada, bob, cy, paid, settled, m1, m2, hold, capture, refund, refundKey, capRefund, memberRefund, late, late2, fix, batch, batchKey, batchBody, snapBefore, snapAfter };
}

async function views(clients: Client[], paymentIds: string[]) {
  return Promise.all(clients.map(async (c) => ({
    me: (await c.get('/me')).body,
    feed: (await c.get('/activity?limit=200')).body,
    statement: (({ snapshot, ...rest }) => rest)((await c.get('/statement?limit=200')).body),
    authorizations: (await c.get('/authorizations?limit=200')).body,
    revisions: await Promise.all(paymentIds.map(async (id) => (await c.get(`/payments/${id}/revisions`)).body)),
  })));
}

describe('export schema 4 (W21.1)', () => {
  it('carries refund_of, correction_batch_id, each snapshot\'s payment form and the keys of the two new paths', async () => {
    const w = await populate();
    const { state: s } = await exportFrom(port);
    assert.equal(s.schema, 4);
    const byId = Object.fromEntries(s.payments.map((p: any) => [p.id, p]));
    assert.equal(byId[w.refund.payment_id].refund_of, w.paid.payment_id);
    assert.equal(byId[w.capRefund.payment_id].refund_of, w.capture.payment_id);
    assert.equal(byId[w.memberRefund.payment_id].refund_of, w.m2.payment_id);
    for (const id of [w.paid.payment_id, w.m1.payment_id, w.capture.payment_id, 'p_seed']) assert.equal(byId[id].refund_of, null);
    assert.deepEqual(byId[w.m2.payment_id].revisions.map((r: any) => r.correction_batch_id), [null, w.batch.correction_batch_id]);
    assert.deepEqual(byId[w.paid.payment_id].revisions.map((r: any) => r.correction_batch_id), [null, null]);
    assert.deepEqual(s.snapshots.map((x: any) => x.payment_form), [4, 4]);
    assert.ok(s.idempotency.some((r: any) => r.path === `/payments/${w.paid.payment_id}/refunds` && r.key === w.refundKey));
    assert.ok(s.idempotency.some((r: any) => r.path === '/correction-batches' && r.key === w.batchKey));
  });
});

describe('schema-4 round trip (W21.2)', () => {
  it('restores refunds, batches, replays and snapshots, here and in another process, and goes on later', async () => {
    const w = await populate();
    const clients = [w.ada, w.bob, w.cy];
    const ids = [w.paid.payment_id, w.m2.payment_id, w.refund.payment_id, w.capture.payment_id];
    const before = await views(clients, ids);
    const snapshot = await exportFrom(port);
    for (const target of [port, second.port]) {
      if (target === port) await reset(port, fixture());
      assert.equal((await importInto(target, snapshot)).status, 204);
      assert.deepEqual(await exportFrom(target), snapshot);
      const [ada, bob, cy] = clients.map((c) => as(c, target));
      assert.deepEqual(await views([ada, bob, cy], ids), before);
      assert.deepEqual((await bob.get(`/statement?snapshot=${w.snapBefore.snapshot}&limit=2`)).body, w.snapBefore);
      assert.deepEqual((await bob.get(`/statement?snapshot=${w.snapAfter.snapshot}&limit=3`)).body, w.snapAfter);
      const refundReplay = await bob.post(`/payments/${w.paid.payment_id}/refunds`, { json: { amount: 200 }, key: w.refundKey });
      assert.deepEqual([refundReplay.status, refundReplay.body], [200, w.refund]);
      const batchReplay = await ada.post('/correction-batches', { json: w.batchBody, key: w.batchKey });
      assert.deepEqual([batchReplay.status, batchReplay.body], [200, w.batch]);
      // The cap still counts the imported refunds: 900 less 200.
      expectError(await bob.post(`/payments/${w.paid.payment_id}/refunds`, { json: { amount: 701 }, key: key() }), 422, 'refund_exceeds_payment');
      expectError(await cy.post(`/payments/${w.refund.payment_id}/refunds`, { json: { amount: 1 }, key: key() }), 403, 'forbidden');
      expectError(await ada.post(`/payments/${w.refund.payment_id}/refunds`, { json: { amount: 1 }, key: key() }), 422, 'invalid_refund_target');
      const more = await post(bob, `/payments/${w.paid.payment_id}/refunds`, { amount: 700 });
      assert.ok(more.created_at > w.batch.recorded_at, 'later than everything imported');
      const next = await post(ada, '/correction-batches', { corrections: [item(w.m1.payment_id, 2, 30, w.settled.committed_at), item(w.m2.payment_id, 2, 5, w.settled.committed_at)] });
      assert.ok(next.recorded_at > more.created_at);
      assert.notEqual(next.correction_batch_id, w.batch.correction_batch_id);
      const alone = { expected_revision: 3, amount: 5, effective_at: w.settled.committed_at, reason: 'x' };
      expectError(await bob.post(`/payments/${w.m2.payment_id}/corrections`, { json: alone, key: key() }), 422, 'linked_payment_immutable');
    }
  });
});

describe('upgrade from the frozen stage-3 build (W21.3, D106)', () => {
  it('pages a stage-3 snapshot exactly as stage 3 did, keeps settlements, revisions and replays, and takes refunds and batches', async () => {
    const p3 = stageThree.port;
    await reset(p3, fixture({ settlement_operator_ids: ['u_ada'] }));
    const [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(p3, h)));
    const payKey = key();
    const paid = await post(ada, '/payments', { to_handle: 'bob', amount: 1_000 }, payKey);
    assert.equal('refund_of' in paid, false, 'this really is a stage-3 build');
    const settleKey = key();
    const settleBody = { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 50 }, { from_handle: 'bob', to_handle: 'cy', amount: 20 }] };
    const settled = await post(ada, '/settlements', settleBody, settleKey);
    const [m1, m2] = settled.payments;
    const hold = await post(ada, '/authorizations', { to_handle: 'bob', amount: 500 });
    const capKey = key();
    const capture = await post(bob, `/authorizations/${hold.authorization_id}/capture`, { amount: 120, final: false }, capKey);
    const fixKey = key();
    const fixBody = { expected_revision: 1, amount: 900, effective_at: paid.created_at, reason: 'less' };
    const fix = await post(ada, `/payments/${paid.payment_id}/corrections`, fixBody, fixKey);
    const page1 = (await bob.get('/statement?limit=2')).body;
    const page2 = (await bob.get(`/statement?snapshot=${page1.snapshot}&limit=2&offset=2`)).body;
    assert.equal(page1.entries.length, 2);
    assert.ok(page1.entries.every((e: any) => !('refund_of' in e.payment)));
    const exported = await exportFrom(p3);
    assert.equal(exported.state.schema, 3);

    assert.equal((await importInto(port, exported)).status, 204);
    const [a4, b4, c4] = [ada, bob, cy].map((c) => as(c, port));
    const pages = async (c: Client) => [
      (await c.get(`/statement?snapshot=${page1.snapshot}&limit=2`)).body,
      (await c.get(`/statement?snapshot=${page1.snapshot}&limit=2&offset=2`)).body,
    ];
    assert.deepEqual(await pages(b4), [page1, page2], 'the stage-3 form, equal as JSON');
    for (const p of (await b4.get('/activity?limit=200')).body.payments) assert.equal(p.refund_of, null);
    // Stored stage-3 bodies replay verbatim, without refund_of.
    for (const [c, path, body, k, original] of [
      [a4, '/payments', { to_handle: 'bob', amount: 1_000 }, payKey, paid],
      [a4, '/settlements', settleBody, settleKey, settled],
      [b4, `/authorizations/${hold.authorization_id}/capture`, { amount: 120, final: false }, capKey, capture],
      [a4, `/payments/${paid.payment_id}/corrections`, fixBody, fixKey, fix],
    ] as const) {
      const replay = await c.post(path, { json: body, key: k });
      assert.deepEqual([replay.status, replay.body], [200, original], path);
    }
    assert.deepEqual((await b4.get(`/payments/${paid.payment_id}/revisions`)).body.revisions.at(-1), fix);

    // A further stage-4 export keeps the snapshot's stage-3 form.
    const again = await exportFrom(port);
    assert.equal(again.state.schema, 4);
    assert.deepEqual(again.state.snapshots.map((x: any) => x.payment_form), [3]);
    assert.equal((await importInto(second.port, again)).status, 204);
    assert.deepEqual(await pages(as(bob, second.port)), [page1, page2]);

    // Settlement membership survived: a batch needs both members; refunds of the imported
    // capture and settlement member work.
    expectError(await a4.post('/correction-batches', { json: { corrections: [item(m1.payment_id, 1, 40, settled.committed_at)] }, key: key() }), 422, 'incomplete_settlement');
    const batch = await post(a4, '/correction-batches', { corrections: [item(m1.payment_id, 1, 40, settled.committed_at), item(m2.payment_id, 1, 15, settled.committed_at)] });
    assert.ok(batch.recorded_at > fix.recorded_at);
    const capRefund = await post(b4, `/payments/${capture.payment_id}/refunds`, { amount: 120 });
    assert.deepEqual([capRefund.refund_of, capRefund.authorization_id, capRefund.settlement_id], [capture.payment_id, null, null]);
    const memberRefund = await post(c4, `/payments/${m2.payment_id}/refunds`, { amount: 15 });
    assert.equal(memberRefund.refund_of, m2.payment_id);
    expectError(await c4.post(`/payments/${m2.payment_id}/refunds`, { json: { amount: 1 }, key: key() }), 422, 'refund_exceeds_payment');
    // The imported snapshot still pages as before; a new one has the stage-4 form.
    assert.deepEqual(await pages(b4), [page1, page2]);
    const fresh = (await b4.get('/statement?limit=200')).body;
    assert.ok(fresh.entries.every((e: any) => 'refund_of' in e.payment));
    assert.ok(fresh.entries.some((e: any) => e.payment.refund_of === capture.payment_id));
    const totals = await Promise.all([a4, b4, c4].map(async (c) => (await c.get('/me')).body.total));
    assert.equal(totals.reduce((x, y) => x + y, 0), 13_000);
  });
});

describe('upgrade from the frozen stage-1 and stage-2 builds (W21.3)', () => {
  it('keeps settlement membership, gives every payment refund_of null and takes refunds and batches', async () => {
    for (const previous of [stageOne, stageTwo]) {
      const p = previous.port;
      await reset(p, fixture({ settlement_operator_ids: ['u_ada'] }));
      const [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(p, h)));
      const paid = await post(ada, '/payments', { to_handle: 'bob', amount: 1_000 });
      await sleep(5);
      const settled = await post(ada, '/settlements', { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 50 }, { from_handle: 'bob', to_handle: 'cy', amount: 20 }] });
      const [m1, m2] = settled.payments;
      let capture: any = null;
      if (previous === stageTwo) {
        await sleep(5);
        const hold = await post(ada, '/authorizations', { to_handle: 'bob', amount: 500 });
        await sleep(5);
        capture = await post(bob, `/authorizations/${hold.authorization_id}/capture`, { amount: 120, final: false });
      }
      const exported = await exportFrom(p);
      assert.equal(exported.state.schema, previous === stageOne ? 1 : 2);
      assert.equal((await importInto(port, exported)).status, 204);
      const [a4, b4, c4] = [ada, bob, cy].map((c) => as(c, port));
      for (const x of (await b4.get('/activity?limit=200')).body.payments) assert.equal(x.refund_of, null);
      expectError(await a4.post('/correction-batches', { json: { corrections: [item(m2.payment_id, 1, 10, settled.committed_at)] }, key: key() }), 422, 'incomplete_settlement');
      await post(a4, '/correction-batches', { corrections: [item(m1.payment_id, 1, 40, settled.committed_at), item(m2.payment_id, 1, 10, settled.committed_at)] });
      const back = await post(b4, `/payments/${paid.payment_id}/refunds`, { amount: 1_000 });
      assert.equal(back.refund_of, paid.payment_id);
      await post(c4, `/payments/${m2.payment_id}/refunds`, { amount: 10 });
      if (capture !== null) assert.equal((await post(b4, `/payments/${capture.payment_id}/refunds`, { amount: 120 })).refund_of, capture.payment_id);
      const totals = await Promise.all([a4, b4, c4].map(async (c) => (await c.get('/me')).body.total));
      assert.equal(totals.reduce((x, y) => x + y, 0), 13_000);
      const again = await exportFrom(port);
      assert.equal((await importInto(second.port, again)).status, 204);
      assert.deepEqual(await exportFrom(second.port), again);
    }
  });
});

describe('invalid schema-4 states (W21.4)', () => {
  it('are 422 and change nothing', async () => {
    const w = await populate();
    const exported = await exportFrom(port);
    const s = exported.state;
    const patch = (fn: (st: any) => void) => {
      const copy = structuredClone(exported);
      fn(copy.state);
      return copy;
    };
    const pay = (st: any, id: string) => st.payments.find((p: any) => p.id === id);
    const user = (st: any, id: string) => st.users.find((u: any) => u.id === id);
    const secondRevision = (p: any) => ({ ...p.revisions[0], revision: 2, recorded_at: later(p.revisions[0].recorded_at), reason: 'x', seq: s.seq });
    const bad: [string, unknown][] = [
      ['schema 5', patch((st) => { st.schema = 5; })],
      ['refund_of not a string', patch((st) => { pay(st, w.refund.payment_id).refund_of = 5; })],
      ['refund_of unknown', patch((st) => { pay(st, w.refund.payment_id).refund_of = 'p_none'; })],
      ['refund_of names a refund', patch((st) => { pay(st, w.late.payment_id).refund_of = w.refund.payment_id; })],
      // late2 is ada -> bob 300, later than the refund: only the order is wrong.
      ['refund_of names a later payment', patch((st) => { pay(st, w.refund.payment_id).refund_of = w.late2.payment_id; })],
      ['refund parties not reversed', patch((st) => { pay(st, w.late.payment_id).refund_of = w.paid.payment_id; })],
      ['refund with a request', patch((st) => { pay(st, w.refund.payment_id).request_id = 'rq_x'; })],
      ['refund with a settlement', patch((st) => { pay(st, w.memberRefund.payment_id).settlement_id = w.settled.settlement_id; })],
      ['refunds above the latest amount', patch((st) => {
        // paid's latest revision down to 150, below its 200 refunded, balances adjusted to match.
        pay(st, w.paid.payment_id).revisions[1].amount = 150;
        user(st, 'u_bob').balance -= 750;
        user(st, 'u_ada').balance += 750;
      })],
      ['a refund with two revisions', patch((st) => { const p = pay(st, w.refund.payment_id); p.revisions.push(secondRevision(p)); })],
      ['a capture with two revisions', patch((st) => { const p = pay(st, w.capture.payment_id); p.revisions.push(secondRevision(p)); })],
      ['one batch at two recorded_at', patch((st) => { pay(st, w.m2.payment_id).revisions[1].recorded_at = later(w.batch.recorded_at); })],
      ['a batch id on revision 1', patch((st) => { pay(st, w.paid.payment_id).revisions[0].correction_batch_id = 'cb_x'; })],
      ['a batch id not a string', patch((st) => { pay(st, w.m2.payment_id).revisions[1].correction_batch_id = 7; })],
      ['payment_form 5', patch((st) => { st.snapshots[0].payment_form = 5; })],
      ['payment_form missing', patch((st) => { delete st.snapshots[0].payment_form; })],
    ];
    assert.equal((await importInto(second.port, exported)).status, 204, 'the unchanged export is valid');
    for (const [name, body] of bad) {
      expectError(await importInto(second.port, body), 422, 'validation_failed');
      assert.deepEqual(await exportFrom(second.port), exported, name);
    }
    // Control: the same change down to exactly the refunded 200 is a valid state.
    const control = patch((st) => {
      pay(st, w.paid.payment_id).revisions[1].amount = 200;
      user(st, 'u_bob').balance -= 700;
      user(st, 'u_ada').balance += 700;
    });
    assert.equal((await importInto(second.port, control)).status, 204);
  });
});
