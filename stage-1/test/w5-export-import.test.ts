// W5: GET /_test/export and POST /_test/import.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, beforeEach, describe, it } from 'node:test';
import {
  Client, expectError, fixture, login, PASSWORD, request, reset, startProcess, startServer, user,
  type Server,
} from './helpers.ts';

let server: Server;
let other: Server; // a second, independent process
let port: number;

before(async () => {
  [server, other] = await Promise.all([startServer(), startProcess()]);
  port = server.port;
});
after(() => Promise.all([server.close(), other.close()]));
beforeEach(() => reset(port, fixture({ settlement_operator_ids: ['u_ada'] })));

const key = () => randomUUID();
const exportFrom = async (p: number) => {
  const reply = await request(p, 'GET', '/_test/export');
  assert.equal(reply.status, 200);
  return reply;
};
const importInto = (p: number, body: unknown) => request(p, 'POST', '/_test/import', { json: body });

// A state with something of every kind: payments, a paid and a pending request, a split,
// a settlement, a signed-up user, several tokens, and successful and failed keys.
async function populate() {
  const ada = await login(port, 'ada');
  const bob = await login(port, 'bob');
  const cy = await login(port, 'cy');
  const keys = { pay: key(), ask: key(), payReq: key(), split: key(), settle: key(), failed: key() };
  const payBody = { to_handle: 'bob', amount: 700, note: 'café 😀', visibility: 'private' };
  const payment = (await ada.post('/payments', { json: payBody, key: keys.pay })).body;
  const ask = (await bob.post('/requests', { json: { payer_handle: 'ada', amount: 300 }, key: keys.ask })).body;
  const paid = (await ada.post(`/requests/${ask.request_id}/pay`, { json: {}, key: keys.payReq })).body;
  const split = (await cy.post('/splits', { json: { amount: 1001, participant_handles: ['cy', 'ada', 'bob'] }, key: keys.split })).body;
  const settlement = (await ada.post('/settlements', {
    json: { transfers: [{ from_handle: 'bob', to_handle: 'cy', amount: 50 }] }, key: keys.settle,
  })).body;
  expectError(await cy.post('/payments', { json: { to_handle: 'ada', amount: 999_999 }, key: keys.failed }), 409, 'insufficient_funds');
  const dee = await request(port, 'POST', '/auth/signup', { json: { email: 'dee@example.com', password: PASSWORD, display_name: 'Dee' } });
  return { ada, bob, cy, dee: new Client(port, dee.body.token), keys, payBody, payment, ask, paid, split, settlement };
}

async function view(clients: Client[]) {
  return Promise.all(clients.map(async (c) => ({
    me: (await c.get('/me')).body,
    activity: (await c.get('/activity?limit=200')).body,
    requests: (await c.get('/requests?limit=200')).body,
  })));
}

describe('GET /_test/export', () => {
  it('is unauthenticated, has the envelope, and holds no plaintext password or token', async () => {
    const w = await populate();
    const reply = await request(port, 'GET', '/_test/export', { headers: { authorization: 'Bearer junk' } });
    assert.equal(reply.status, 200);
    assert.equal(reply.body.track, 'pocketful');
    assert.equal(reply.body.format_version, 1);
    assert.equal(typeof reply.body.state, 'object');
    assert.ok(!reply.text.includes(PASSWORD), 'no plaintext password');
    assert.ok(!reply.text.includes(w.ada.token!), 'no bearer token');
    for (const u of reply.body.state.users) assert.equal(u.password.alg, 'scrypt');
  });

  it('is a snapshot: later writes do not change it, and importing it restores that point', async () => {
    const w = await populate();
    const before = await view([w.ada, w.bob, w.cy, w.dee]);
    const snapshot = (await exportFrom(port)).body;
    const again = (await exportFrom(port)).body;
    assert.deepEqual(again, snapshot);
    await w.ada.post('/payments', { json: { to_handle: 'cy', amount: 1 }, key: key() });
    assert.notDeepEqual((await exportFrom(port)).body, snapshot);
    assert.equal((await importInto(port, snapshot)).status, 204);
    assert.deepEqual(await view([w.ada, w.bob, w.cy, w.dee]), before);
  });
});

describe('POST /_test/import', () => {
  for (const target of ['the same process after a reset', 'a second process']) {
    it(`restores everything into ${target}`, async () => {
      const w = await populate();
      const before = await view([w.ada, w.bob, w.cy, w.dee]);
      const snapshot = (await exportFrom(port)).body;
      const p = target === 'a second process' ? other.port : port;
      if (p === port) await reset(port);
      else await reset(p, fixture({ users: [user('zed', 5)] }));
      const zedToken = p === port ? null : (await login(p, 'zed')).token;
      assert.equal((await importInto(p, snapshot)).status, 204);
      assert.equal((await importInto(p, snapshot)).status, 204, 'importing twice is the same as once');
      const [ada, bob, cy, dee] = [w.ada, w.bob, w.cy, w.dee].map((c) => new Client(p, c.token));

      // Tokens, feeds, request lists and balances are identical.
      assert.deepEqual(await view([ada, bob, cy, dee]), before);
      // Logins work with the imported hashes; earlier destination users and tokens are gone.
      assert.equal((await login(p, 'bob')).token!.length > 40, true);
      assert.equal((await request(p, 'POST', '/auth/login', { json: { email: 'dee@example.com', password: PASSWORD } })).status, 200);
      if (zedToken) {
        expectError(await new Client(p, zedToken).get('/me'), 401, 'unauthenticated');
        expectError(await request(p, 'POST', '/auth/login', { json: { email: 'zed@example.com', password: PASSWORD } }), 401, 'unauthenticated');
      }
      // Replays of earlier keys return 200 with the original bodies and move nothing.
      const replays: Array<[Client, string, unknown, string, unknown]> = [
        [ada, '/payments', w.payBody, w.keys.pay, w.payment],
        [bob, '/requests', { payer_handle: 'ada', amount: 300 }, w.keys.ask, w.ask],
        [ada, `/requests/${w.ask.request_id}/pay`, {}, w.keys.payReq, w.paid],
        [cy, '/splits', { amount: 1001, participant_handles: ['cy', 'ada', 'bob'] }, w.keys.split, w.split],
        [ada, '/settlements', { transfers: [{ from_handle: 'bob', to_handle: 'cy', amount: 50 }] }, w.keys.settle, w.settlement],
      ];
      for (const [client, path, json, k, original] of replays) {
        const reply = await client.post(path, { json, key: k });
        assert.equal(reply.status, 200, `${path}: ${reply.text}`);
        assert.deepEqual(reply.body, original);
      }
      expectError(await ada.post('/payments', { json: { ...w.payBody, amount: 701 }, key: w.keys.pay }), 409, 'idempotency_key_reuse');
      assert.deepEqual(await view([ada, bob, cy, dee]), before);
      // The key that failed before the export is a first use.
      assert.equal((await cy.post('/payments', { json: { to_handle: 'ada', amount: 1 }, key: w.keys.failed })).status, 201);
      // Pending split requests stay payable; operator permission survives.
      const pending = w.split.requests.find((r: any) => r.payer_handle === 'bob');
      assert.equal((await bob.post(`/requests/${pending.request_id}/pay`, { json: {}, key: key() })).status, 201);
      assert.equal((await ada.post('/settlements', { json: { transfers: [{ from_handle: 'cy', to_handle: 'bob', amount: 1 }] }, key: key() })).status, 201);
      expectError(await bob.post('/settlements', { json: { transfers: [{ from_handle: 'cy', to_handle: 'bob', amount: 1 }] }, key: key() }), 403, 'forbidden');
      // New ids never collide and new timestamps are not earlier than imported ones.
      const fresh = (await ada.post('/payments', { json: { to_handle: 'bob', amount: 1 }, key: key() })).body;
      const exported = snapshot.state;
      const ids = new Set(exported.payments.map((x: any) => x.id));
      assert.ok(!ids.has(fresh.payment_id));
      const latest = exported.payments.map((x: any) => x.created_at).sort().at(-1);
      assert.ok(fresh.created_at >= latest);
      const sum = (await Promise.all([ada, bob, cy, dee].map(async (c) => (await c.get('/me')).body.balance))).reduce((a, b) => a + b, 0);
      assert.equal(sum, 13_000);
    });
  }

  it('a reset after an import clears it', async () => {
    const w = await populate();
    const snapshot = (await exportFrom(port)).body;
    await importInto(port, snapshot);
    await reset(port, fixture({ users: [user('zed', 1)] }));
    expectError(await w.ada.get('/me'), 401, 'unauthenticated');
    assert.equal((await exportFrom(port)).body.state.users.length, 1);
  });

  it('rejects invalid imports and leaves the destination unchanged', async () => {
    const w = await populate();
    const snapshot = (await exportFrom(port)).body;
    const before = await view([w.ada, w.bob, w.cy, w.dee]);
    const s = snapshot.state;
    const users = s.users;
    const bad: unknown[] = [
      {}, { format_version: 1, state: s }, { track: 'pocketful', state: s }, { track: 'pocketful', format_version: 1 },
      { ...snapshot, track: 'other' }, { ...snapshot, format_version: 2 }, { ...snapshot, format_version: '1' },
      { ...snapshot, state: [] }, { ...snapshot, state: 'x' }, { ...snapshot, state: { ...s, schema: 2 } },
      { ...snapshot, state: { ...s, users: [{ ...users[0], balance: -1 }, ...users.slice(1)] } },
      { ...snapshot, state: { ...s, payments: [{ ...s.payments[0], to_user_id: 'u_ghost' }, ...s.payments.slice(1)] } },
      { ...snapshot, state: { ...s, tokens: [{ digest: 'x', user_id: 'u_ada' }] } },
      { ...snapshot, state: { ...s, users: [...users, users[0]] } },
      { ...snapshot, state: { ...s, requests: [{ ...s.requests[0], status: 'open' }] } },
      { ...snapshot, state: { ...s, operator_ids: ['u_ghost'] } },
      { ...snapshot, state: { ...s, idempotency: 'x' } },
      { ...snapshot, state: { ...s, users: [{ ...users[0], password: 'correct horse' }, ...users.slice(1)] } },
    ];
    for (const body of bad) expectError(await importInto(port, body), 422, 'validation_failed');
    expectError(await request(port, 'POST', '/_test/import', { raw: '{nope' }), 400, 'malformed_request');
    expectError(await request(port, 'POST', '/_test/import', { raw: '[]' }), 400, 'malformed_request');
    assert.deepEqual(await view([w.ada, w.bob, w.cy, w.dee]), before);
  });

  it('accepts an export holding a stored body nested 64 levels deep', async () => {
    const ada = await login(port, 'ada');
    let deep: unknown = 1;
    for (let i = 0; i < 62; i++) deep = [deep];
    const k = key();
    assert.equal((await ada.post('/payments', { json: { to_handle: 'bob', amount: 1, extra: deep }, key: k })).status, 201);
    const snapshot = (await exportFrom(port)).body;
    assert.equal((await importInto(port, snapshot)).status, 204);
    assert.equal((await ada.post('/payments', { json: { to_handle: 'bob', amount: 1, extra: deep }, key: k })).status, 200);
  });
});
