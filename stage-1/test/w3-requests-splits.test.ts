// W3: payment requests (create, pay, decline, cancel, list) and splits.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, beforeEach, describe, it } from 'node:test';
import {
  Client, expectError, fixture, login, request, reset, startServer, user,
  type Server,
} from './helpers.ts';

let server: Server;
let port: number;
let ada: Client;
let bob: Client;
let cy: Client;

before(async () => {
  server = await startServer();
  port = server.port;
});
after(() => server.close());
beforeEach(async () => {
  await reset(port);
  [ada, bob, cy] = await Promise.all([login(port, 'ada'), login(port, 'bob'), login(port, 'cy')]);
});

const key = () => randomUUID();
const balance = async (client: Client) => (await client.get('/me')).body.balance as number;
const total = async () => (await Promise.all([ada, bob, cy].map(balance))).reduce((a, b) => a + b, 0);
// `requester` asks `payerHandle` for money.
const ask = (requester: Client, json: Record<string, unknown>, k: string = key()) =>
  requester.post('/requests', { json, key: k });
const askOk = async (requester: Client, payerHandle: string, amount: number, note?: string) => {
  const reply = await ask(requester, note === undefined ? { payer_handle: payerHandle, amount } : { payer_handle: payerHandle, amount, note });
  assert.equal(reply.status, 201, reply.text);
  return reply.body;
};
const payReq = (payer: Client, id: string, json: unknown = {}, k: string = key()) =>
  payer.post(`/requests/${id}/pay`, { json, key: k });
const split = (client: Client, json: unknown, k: string = key()) => client.post('/splits', { json, key: k });

const REQUEST_FIELDS = [
  'amount', 'created_at', 'currency', 'note', 'payer_handle', 'payer_id', 'payment_id', 'request_id',
  'requester_handle', 'requester_id', 'status',
];

describe('POST /requests', () => {
  it('creates a pending request with exactly the request fields, even above the payer balance', async () => {
    const reply = await ask(bob, { payer_handle: 'ada', amount: 50_000, note: 'taxi', visibility: 'secret' });
    assert.equal(reply.status, 201);
    assert.deepEqual(Object.keys(reply.body).sort(), REQUEST_FIELDS);
    assert.equal(reply.body.requester_id, 'u_bob');
    assert.equal(reply.body.requester_handle, 'bob');
    assert.equal(reply.body.payer_id, 'u_ada');
    assert.equal(reply.body.payer_handle, 'ada');
    assert.equal(reply.body.amount, 50_000);
    assert.equal(reply.body.currency, 'EUR');
    assert.equal(reply.body.note, 'taxi');
    assert.equal(reply.body.status, 'pending');
    assert.equal(reply.body.payment_id, null);
    assert.equal(await balance(ada), 10_000);
    assert.equal((await ask(bob, { payer_handle: 'ada', amount: 1 })).body.note, '');
  });

  it('applies the field rules and precedence', async () => {
    for (const amount of [0, -1, 1.5, 1_000_000_001, '100', true, null]) {
      expectError(await ask(bob, { payer_handle: 'ada', amount }), 422, 'validation_failed');
    }
    expectError(await ask(bob, { payer_handle: 'ada' }), 422, 'validation_failed');
    expectError(await ask(bob, { amount: 1 }), 422, 'validation_failed');
    expectError(await ask(bob, { payer_handle: null, amount: 0 }), 400, 'malformed_request');
    expectError(await ask(bob, { payer_handle: 'ada', amount: 1, note: 'x'.repeat(201) }), 422, 'validation_failed');
    expectError(await ask(bob, { payer_handle: 'ada', amount: 1, note: null }), 422, 'validation_failed');
    for (const handle of ['nobody', 'ADA', '@ada', '']) {
      expectError(await ask(bob, { payer_handle: handle, amount: 1 }), 404, 'not_found');
    }
    expectError(await ask(bob, { payer_handle: 'bob', amount: 1 }), 422, 'self_request');
    expectError(await bob.post('/requests', { json: { payer_handle: 'ada', amount: 1 } }), 400, 'missing_idempotency_key');
  });

  it('replays, refuses reuse, and scopes keys per path', async () => {
    const k = key();
    const first = await ask(bob, { payer_handle: 'ada', amount: 7 }, k);
    const replay = await ask(bob, { amount: 7.0, payer_handle: 'ada' }, k);
    assert.equal(replay.status, 200);
    assert.deepEqual(replay.body, first.body);
    expectError(await ask(bob, { payer_handle: 'ada', amount: 8 }, k), 409, 'idempotency_key_reuse');
    assert.equal((await bob.get('/requests')).body.requests.length, 1);
    const shared = 'shared-across-paths';
    assert.equal((await ada.post('/payments', { json: { to_handle: 'bob', amount: 10 }, key: shared })).status, 201);
    assert.equal((await ask(ada, { payer_handle: 'bob', amount: 10 }, shared)).status, 201);
    assert.equal((await split(ada, { amount: 10, participant_handles: ['bob'] }, shared)).status, 201);
  });
});

describe('POST /requests/{id}/pay', () => {
  it('pays: a payment receipt with request_id, and the request becomes paid', async () => {
    const rq = await askOk(bob, 'ada', 1200, 'taxi');
    const reply = await payReq(ada, rq.request_id, { visibility: 'private' });
    assert.equal(reply.status, 201);
    const p = reply.body;
    assert.equal(p.request_id, rq.request_id);
    assert.equal(p.settlement_id, null);
    assert.equal(p.from_handle, 'ada');
    assert.equal(p.to_handle, 'bob');
    assert.equal(p.amount, 1200);
    assert.equal(p.note, 'taxi');
    assert.equal(p.visibility, 'private');
    assert.equal(await balance(ada), 8800);
    assert.equal(await balance(bob), 3700);
    const listed = (await ada.get('/requests')).body.requests[0];
    assert.equal(listed.status, 'paid');
    assert.equal(listed.payment_id, p.payment_id);
    assert.deepEqual((await bob.get('/activity')).body.payments, [p]);
    assert.deepEqual((await cy.get('/activity')).body.payments, []);
    const rq2 = await askOk(bob, 'ada', 1);
    assert.equal((await payReq(ada, rq2.request_id, {})).body.visibility, 'public');
  });

  it('checks errors in the order 422, 404, 403, 409 not pending, 409 funds', async () => {
    const rq = await askOk(ada, 'cy', 600);
    expectError(await payReq(cy, 'rq_nope', { visibility: 'secret' }), 422, 'validation_failed');
    expectError(await payReq(cy, 'rq_nope'), 404, 'not_found');
    expectError(await payReq(ada, rq.request_id), 403, 'forbidden');
    expectError(await payReq(bob, rq.request_id), 403, 'forbidden');
    expectError(await payReq(cy, rq.request_id), 409, 'insufficient_funds');
    assert.equal(await balance(cy), 500);
    assert.equal((await cy.get('/requests')).body.requests[0].status, 'pending');
    assert.equal((await cy.post(`/requests/${rq.request_id}/decline`)).status, 200);
    expectError(await payReq(cy, rq.request_id), 409, 'request_not_pending');
    expectError(await cy.post(`/requests/${rq.request_id}/pay`, { json: {} }), 400, 'missing_idempotency_key');
  });

  it('replays a successful pay with 200 and the original, never 409', async () => {
    const rq = await askOk(bob, 'ada', 100);
    const k = key();
    const first = await payReq(ada, rq.request_id, {}, k);
    const replay = await payReq(ada, rq.request_id, {}, k);
    assert.equal(replay.status, 200);
    assert.deepEqual(replay.body, first.body);
    expectError(await payReq(ada, rq.request_id, { visibility: 'public' }, k), 409, 'idempotency_key_reuse');
    expectError(await payReq(ada, rq.request_id, {}, key()), 409, 'request_not_pending');
    assert.equal(await balance(ada), 9900);
    const rq2 = await askOk(bob, 'ada', 100);
    const k2 = key();
    assert.equal((await payReq(ada, rq2.request_id, { visibility: 'public' }, k2)).status, 201);
    expectError(await payReq(ada, rq2.request_id, {}, k2), 409, 'idempotency_key_reuse');
  });

  it('a key refused for funds is reusable after funding and pays once', async () => {
    const rq = await askOk(ada, 'cy', 1500);
    const k = key();
    expectError(await payReq(cy, rq.request_id, {}, k), 409, 'insufficient_funds');
    assert.equal((await ada.post('/payments', { json: { to_handle: 'cy', amount: 1000 }, key: key() })).status, 201);
    assert.equal((await payReq(cy, rq.request_id, {}, k)).status, 201);
    assert.equal((await payReq(cy, rq.request_id, {}, k)).status, 200);
    const paid = (await cy.get('/activity?limit=200')).body.payments.filter((p: any) => p.request_id === rq.request_id);
    assert.equal(paid.length, 1);
    assert.equal(await total(), 13_000);
  });

  it('seeded requests: pending ones are payable, others are 409', async () => {
    await reset(port, fixture({
      requests: [
        { id: 'rq_seed', requester_id: 'u_bob', payer_id: 'u_ada', amount: 1200, note: 'taxi', status: 'pending' },
        { id: 'rq_done', requester_id: 'u_bob', payer_id: 'u_ada', amount: 5, status: 'declined' },
      ],
    }));
    const a = await login(port, 'ada');
    const listed = (await a.get('/requests')).body.requests;
    assert.deepEqual(listed.map((r: any) => [r.request_id, r.status]), [['rq_done', 'declined'], ['rq_seed', 'pending']]);
    expectError(await payReq(a, 'rq_done'), 409, 'request_not_pending');
    const paid = await payReq(a, 'rq_seed');
    assert.equal(paid.status, 201);
    assert.equal(paid.body.amount, 1200);
    assert.equal(await balance(a), 8800);
  });

  it('20 concurrent pays with distinct keys: one 201, the rest request_not_pending', async () => {
    const rq = await askOk(bob, 'ada', 100);
    const clients = await Promise.all(Array.from({ length: 20 }, () => login(port, 'ada')));
    const replies = await Promise.all(clients.map((c) => payReq(c, rq.request_id)));
    assert.equal(replies.filter((r) => r.status === 201).length, 1);
    for (const r of replies.filter((x) => x.status !== 201)) expectError(r, 409, 'request_not_pending');
    assert.equal(await balance(ada), 9900);
    assert.equal(await total(), 13_000);
  });

  it('concurrent pay and decline, and pay and cancel, have exactly one winner', async () => {
    for (const [loser, action] of [[() => ada, 'decline'], [() => bob, 'cancel']] as const) {
      const rq = await askOk(bob, 'ada', 100);
      const before = await balance(ada);
      const [paid, other] = await Promise.all([payReq(ada, rq.request_id), loser().post(`/requests/${rq.request_id}/${action}`)]);
      assert.equal([paid.status === 201, other.status === 200].filter(Boolean).length, 1, `${paid.status} ${other.status}`);
      const status = (await ada.get('/requests')).body.requests.find((r: any) => r.request_id === rq.request_id).status;
      if (paid.status === 201) {
        assert.equal(status, 'paid');
        expectError(other, 409, 'request_not_pending');
        assert.equal(await balance(ada), before - 100);
      } else {
        expectError(paid, 409, 'request_not_pending');
        assert.equal(await balance(ada), before);
      }
    }
  });
});

describe('decline and cancel', () => {
  it('moves pending to declined or cancelled; repeating is 200; other final states are 409', async () => {
    const r1 = await askOk(bob, 'ada', 100);
    const declined = await ada.post(`/requests/${r1.request_id}/decline`, { raw: '{not json' });
    assert.equal(declined.status, 200);
    assert.deepEqual(Object.keys(declined.body).sort(), REQUEST_FIELDS);
    assert.equal(declined.body.status, 'declined');
    assert.deepEqual((await ada.post(`/requests/${r1.request_id}/decline`)).body, declined.body);
    expectError(await bob.post(`/requests/${r1.request_id}/cancel`), 409, 'request_not_pending');

    const r2 = await askOk(bob, 'ada', 100);
    assert.equal((await bob.post(`/requests/${r2.request_id}/cancel`)).body.status, 'cancelled');
    assert.equal((await bob.post(`/requests/${r2.request_id}/cancel`)).status, 200);
    expectError(await ada.post(`/requests/${r2.request_id}/decline`), 409, 'request_not_pending');
    expectError(await payReq(ada, r2.request_id), 409, 'request_not_pending');

    const r3 = await askOk(bob, 'ada', 100);
    assert.equal((await payReq(ada, r3.request_id)).status, 201);
    expectError(await ada.post(`/requests/${r3.request_id}/decline`), 409, 'request_not_pending');
    expectError(await bob.post(`/requests/${r3.request_id}/cancel`), 409, 'request_not_pending');
  });

  it('only the payer declines and only the requester cancels; unknown is 404; 401 without a token', async () => {
    const rq = await askOk(bob, 'ada', 100);
    expectError(await bob.post(`/requests/${rq.request_id}/decline`), 403, 'forbidden');
    expectError(await cy.post(`/requests/${rq.request_id}/decline`), 403, 'forbidden');
    expectError(await ada.post(`/requests/${rq.request_id}/cancel`), 403, 'forbidden');
    expectError(await cy.post(`/requests/${rq.request_id}/cancel`), 403, 'forbidden');
    expectError(await ada.post('/requests/rq_nope/decline'), 404, 'not_found');
    expectError(await bob.post('/requests/rq_nope/cancel'), 404, 'not_found');
    expectError(await request(port, 'POST', `/requests/${rq.request_id}/decline`), 401, 'unauthenticated');
    assert.equal((await ada.get('/requests')).body.requests[0].status, 'pending');
  });
});

describe('GET /requests', () => {
  it('returns only requests where the caller is a party, under every filter', async () => {
    await askOk(bob, 'ada', 100);
    await askOk(ada, 'bob', 200);
    for (const q of ['', '?direction=incoming', '?direction=outgoing', '?status=pending', '?status=paid', '?limit=200']) {
      assert.deepEqual((await cy.get(`/requests${q}`)).body, { requests: [], has_more: false });
    }
  });

  it('filters by direction and status, alone and together, newest first', async () => {
    const a = await askOk(bob, 'ada', 1); // incoming for ada
    const b = await askOk(ada, 'bob', 2); // outgoing for ada
    const c = await askOk(cy, 'ada', 3); // incoming for ada
    await ada.post(`/requests/${c.request_id}/decline`);
    const ids = async (q: string) => (await ada.get(`/requests${q}`)).body.requests.map((r: any) => r.request_id);
    assert.deepEqual(await ids(''), [c.request_id, b.request_id, a.request_id]);
    assert.deepEqual(await ids('?direction=incoming'), [c.request_id, a.request_id]);
    assert.deepEqual(await ids('?direction=outgoing'), [b.request_id]);
    assert.deepEqual(await ids('?status=declined'), [c.request_id]);
    assert.deepEqual(await ids('?direction=incoming&status=pending'), [a.request_id]);
    assert.deepEqual(await ids('?direction=outgoing&status=declined'), []);
    const times = (await ada.get('/requests')).body.requests.map((r: any) => r.created_at);
    assert.deepEqual(times, times.slice().sort().reverse());
  });

  it('pages with limit, offset and has_more; refuses invalid parameters with 422', async () => {
    for (let i = 0; i < 3; i++) await askOk(bob, 'ada', 100 + i);
    const p1 = (await ada.get('/requests?limit=2&offset=0')).body;
    assert.equal(p1.requests.length, 2);
    assert.equal(p1.has_more, true);
    const p2 = (await ada.get('/requests?limit=2&offset=2')).body;
    assert.equal(p2.requests.length, 1);
    assert.equal(p2.has_more, false);
    for (const q of ['direction=both', 'direction=', 'direction=Incoming', 'status=open', 'status=', 'status=PENDING',
      'limit=0', 'limit=201', 'limit=-5', 'limit=1e9', 'offset=-1', 'offset=abc']) {
      expectError(await ada.get(`/requests?${q}`), 422, 'validation_failed');
    }
    expectError(await request(port, 'GET', '/requests'), 401, 'unauthenticated');
  });
});

describe('POST /splits', () => {
  it('follows the equal-split table of §9', async () => {
    const table: Array<[number, number, number[]]> = [
      [1000, 3, [334, 333, 333]], [1, 3, [1, 0, 0]], [10, 3, [4, 3, 3]], [999, 3, [333, 333, 333]], [5, 5, [1, 1, 1, 1, 1]],
    ];
    await reset(port, fixture({ users: ['ada', 'bob', 'cy', 'dee', 'eve'].map((h) => user(h, 100)) }));
    const a = await login(port, 'ada');
    for (const [amount, n, shares] of table) {
      const handles = ['ada', 'bob', 'cy', 'dee', 'eve'].slice(0, n);
      const reply = await split(a, { amount, participant_handles: handles });
      assert.equal(reply.status, 201, reply.text);
      assert.deepEqual(reply.body.shares, handles.map((handle, i) => ({ handle, amount: shares[i] })));
      assert.deepEqual(reply.body.requests.map((r: any) => [r.payer_handle, r.amount]),
        handles.slice(1).map((h, i) => [h, shares[i + 1]]));
    }
  });

  it('returns the split representation with its pending requests', async () => {
    const reply = await split(ada, { amount: 3000, participant_handles: ['bob', 'ada', 'cy'], note: 'dinner' });
    assert.equal(reply.status, 201);
    const body = reply.body;
    assert.deepEqual(Object.keys(body).sort(), ['amount', 'created_at', 'currency', 'note', 'requests', 'shares', 'split_id']);
    assert.equal(body.amount, 3000);
    assert.equal(body.currency, 'EUR');
    assert.equal(body.note, 'dinner');
    assert.deepEqual(body.shares, [{ handle: 'bob', amount: 1000 }, { handle: 'ada', amount: 1000 }, { handle: 'cy', amount: 1000 }]);
    assert.deepEqual(body.requests.map((r: any) => r.payer_handle), ['bob', 'cy']);
    for (const r of body.requests) {
      assert.deepEqual(Object.keys(r).sort(), REQUEST_FIELDS);
      assert.equal(r.requester_handle, 'ada');
      assert.equal(r.status, 'pending');
      assert.equal(r.note, 'dinner');
      assert.equal(r.created_at, body.created_at);
    }
    const bobs = (await bob.get('/requests')).body.requests;
    assert.deepEqual(bobs, [body.requests[0]]);
    assert.deepEqual((await ada.get('/activity')).body.payments, []);
  });

  it('moves the extra unit with handle order; caller listed or not; a caller-only split creates no requests', async () => {
    const first = (await split(ada, { amount: 1000, participant_handles: ['ada', 'bob', 'cy'] })).body;
    const second = (await split(ada, { amount: 1000, participant_handles: ['cy', 'bob', 'ada'] })).body;
    assert.deepEqual(first.shares[0], { handle: 'ada', amount: 334 });
    assert.deepEqual(second.shares[0], { handle: 'cy', amount: 334 });
    const without = (await split(ada, { amount: 10, participant_handles: ['bob', 'cy'] })).body;
    assert.deepEqual(without.shares, [{ handle: 'bob', amount: 5 }, { handle: 'cy', amount: 5 }]);
    assert.equal(without.requests.length, 2);
    const alone = (await split(ada, { amount: 999, participant_handles: ['ada'] })).body;
    assert.deepEqual(alone.shares, [{ handle: 'ada', amount: 999 }]);
    assert.deepEqual(alone.requests, []);
  });

  it('zero shares still create requests, and a zero request is payable with a payment of 0', async () => {
    const body = (await split(ada, { amount: 1, participant_handles: ['ada', 'bob', 'cy'] })).body;
    assert.deepEqual(body.requests.map((r: any) => r.amount), [0, 0]);
    const paid = await payReq(bob, body.requests[0].request_id);
    assert.equal(paid.status, 201);
    assert.equal(paid.body.amount, 0);
    assert.equal(await balance(bob), 2500);
  });

  it('validates the participant list and fields', async () => {
    for (const handles of [[], ['ada', 'ada'], Array.from({ length: 201 }, (_, i) => `h${i}`),
      Array.from({ length: 1000 }, (_, i) => `h${i}`)]) {
      expectError(await split(ada, { amount: 100, participant_handles: handles }), 422, 'validation_failed');
    }
    expectError(await split(ada, { amount: 100 }), 422, 'validation_failed');
    for (const handles of ['ada', null, ['ada', 5], { a: 1 }]) {
      expectError(await split(ada, { amount: 100, participant_handles: handles }), 400, 'malformed_request');
    }
    expectError(await split(ada, { amount: '100', participant_handles: 'ada' }), 400, 'malformed_request');
    for (const amount of [0, -1, 1_000_000_001, '100', 1.5]) {
      expectError(await split(ada, { amount, participant_handles: ['ada', 'bob'] }), 422, 'validation_failed');
    }
    expectError(await split(ada, { amount: 100, participant_handles: ['ada', 'bob'], note: 'x'.repeat(201) }), 422, 'validation_failed');
    expectError(await split(ada, { amount: 100, participant_handles: ['ada', 'nobody', 'ghost'] }), 404, 'not_found');
    assert.deepEqual((await bob.get('/requests')).body.requests, []);
  });

  it('checks nobody balance, replays, and conserves money once every request is paid', async () => {
    assert.equal((await split(cy, { amount: 1_000_000, participant_handles: ['cy', 'ada'] })).status, 201);
    const k = key();
    const first = await split(ada, { amount: 1001, participant_handles: ['ada', 'bob', 'cy'] }, k);
    const replay = await split(ada, { participant_handles: ['ada', 'bob', 'cy'], amount: 1001 }, k);
    assert.equal(replay.status, 200);
    assert.deepEqual(replay.body, first.body);
    expectError(await split(ada, { amount: 1001, participant_handles: ['ada', 'cy', 'bob'] }, k), 409, 'idempotency_key_reuse');
    for (const [client, r] of [[bob, first.body.requests[0]], [cy, first.body.requests[1]]] as const) {
      assert.equal((await payReq(client, r.request_id)).status, 201);
    }
    // The replay still returns the original pending requests.
    const later = await split(ada, { amount: 1001, participant_handles: ['ada', 'bob', 'cy'] }, k);
    assert.deepEqual(later.body, first.body);
    assert.equal(await total(), 13_000);
    assert.equal(await balance(ada), 10_000 + 334 + 333);
  });
});
