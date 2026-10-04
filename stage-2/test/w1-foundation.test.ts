// W1: transport, errors, reset, authentication and GET /me.

import assert from 'node:assert/strict';
import http from 'node:http';
import { after, before, beforeEach, describe, it } from 'node:test';
import {
  Client, expectError, fixture, login, PASSWORD, request, reset, startServer, user,
  type Server,
} from './helpers.ts';

let server: Server;
let port: number;

before(async () => {
  server = await startServer();
  port = server.port;
});
after(() => server.close());
beforeEach(() => reset(port));

const signup = (email: string, password = PASSWORD, displayName = 'Someone') =>
  request(port, 'POST', '/auth/signup', { json: { email, password, display_name: displayName } });

describe('transport', () => {
  it('serves health as JSON', async () => {
    const reply = await request(port, 'GET', '/health');
    assert.equal(reply.status, 200);
    assert.deepEqual(reply.body, { status: 'ok' });
    assert.equal(reply.headers['content-type'], 'application/json; charset=utf-8');
  });

  it('answers unknown paths and unsupported methods with 404 not_found', async () => {
    expectError(await request(port, 'GET', '/nope'), 404, 'not_found');
    expectError(await request(port, 'DELETE', '/me'), 404, 'not_found');
    expectError(await request(port, 'GET', '/auth/login'), 404, 'not_found');
    expectError(await request(port, 'GET', '/me/'), 404, 'not_found');
  });

  it('answers paths that do not percent-decode with 404, never 5xx (D33)', async () => {
    const ada = await login(port, 'ada');
    for (const path of ['/requests/%E0%A4%A/pay', '/requests/%ZZ/decline', '/requests/%/cancel', '/m%65', '/%E0%A4%A']) {
      expectError(await ada.post(path, { json: {}, key: 'k' }), 404, 'not_found');
      expectError(await ada.get(path), 404, 'not_found');
    }
  });

  it('keeps an idle keep-alive connection open past 6 s (D35)', async () => {
    const agent = new http.Agent({ keepAlive: true, maxSockets: 1 });
    const get = () => new Promise<{ status: number; reused: boolean }>((resolve, reject) => {
      const req = http.get({ host: '127.0.0.1', port, path: '/health', agent }, (res) => {
        res.resume();
        res.on('end', () => resolve({ status: res.statusCode ?? 0, reused: req.reusedSocket }));
      });
      req.on('error', reject);
    });
    try {
      assert.deepEqual(await get(), { status: 200, reused: false });
      await new Promise((resolve) => setTimeout(resolve, 6_000));
      assert.deepEqual(await get(), { status: 200, reused: true });
    } finally {
      agent.destroy();
    }
  });

  it('refuses unreadable bodies with 400 malformed_request', async () => {
    const bad: Array<string | Buffer> = [
      '', '   ', '{nope', '[]', '"text"', '42', 'null',
      Buffer.from([0x7b, 0x22, 0x61, 0x22, 0x3a, 0x22, 0xff, 0x22, 0x7d]), // invalid UTF-8
      '{"email": "\\ud800@example.com", "password": "x"}', // unpaired surrogate
      `{"a": ${'['.repeat(64)}${']'.repeat(64)}}`, // 65 levels
    ];
    for (const raw of bad) {
      expectError(await request(port, 'POST', '/auth/login', { raw }), 400, 'malformed_request');
    }
  });

  it('accepts nesting of exactly 64 levels', async () => {
    const raw = `{"email": "nobody@example.com", "password": "correct horse", "x": ${'['.repeat(63)}${']'.repeat(63)}}`;
    expectError(await request(port, 'POST', '/auth/login', { raw }), 401, 'unauthenticated');
  });

  it('refuses a body over 1 MiB on API endpoints with 422', async () => {
    const raw = JSON.stringify({ email: 'ada@example.com', password: 'x'.repeat(1024 * 1024) });
    expectError(await request(port, 'POST', '/auth/login', { raw }), 422, 'validation_failed');
  });

  it('accepts large header blocks and refuses oversized ones with the envelope', async () => {
    const ok = await request(port, 'GET', '/health', { headers: { 'x-pad': 'a'.repeat(200 * 1024) } });
    assert.equal(ok.status, 200);
    const tooBig = await request(port, 'GET', '/health', { headers: { 'x-pad': 'a'.repeat(1100 * 1024) } });
    expectError(tooBig, 422, 'validation_failed');
  });
});

describe('reset', () => {
  it('rejects every invalid fixture with 422 and leaves the previous state intact', async () => {
    const ada = await login(port, 'ada');
    const base = fixture();
    const users = base.users as Array<Record<string, unknown>>;
    const broken: unknown[] = [
      { ...base, currency: 'eur' },
      { ...base, currency: 7 },
      { ...base, minor_units: 1 },
      { ...base, minor_units: '2' },
      { ...base, users: undefined },
      { ...base, users: 'nope' },
      { ...base, users: [user('ada', -1)] },
      { ...base, users: [user('ada', 1.5)] },
      { ...base, users: [user('ada', 2 ** 53 + 2)] },
      { ...base, users: [user('ada', 1), user('ada', 1, { id: 'u_other', email: 'other@example.com' })] },
      { ...base, users: [user('ada', 1), user('bob', 1, { id: 'u_ada' })] },
      { ...base, users: [user('ada', 1), user('bob', 1, { email: 'ADA@example.com' })] },
      { ...base, users: [user('ada', 1, { handle: 'Ada' })] },
      { ...base, users: [user('ada', 1, { email: 'no-at-sign' })] },
      { ...base, users: [user('ada', 1, { password: '' })] },
      { ...base, users: [user('ada', 1, { id: 'x'.repeat(65) })] },
      { ...base, payments: [{ id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_nobody', amount: 1 }] },
      { ...base, payments: [{ id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_ada', amount: 1 }] },
      { ...base, payments: [{ id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1, visibility: 'secret' }] },
      { ...base, requests: [{ id: 'rq_1', requester_id: 'u_bob', payer_id: 'u_ada', amount: 1, status: 'open' }] },
      { ...base, requests: [{ id: 'rq_1', requester_id: 'u_bob', payer_id: 'u_ada', amount: -1 }] },
      { ...base, settlement_operator_ids: ['u_nobody'] },
      { ...base, users: users.concat(Array.from({ length: 1001 }, (_, i) => user(`x${i}`, 0))) },
    ];
    for (const body of broken) {
      const reply = await request(port, 'POST', '/_test/reset', { json: body });
      expectError(reply, 422, 'validation_failed');
    }
    expectError(await request(port, 'POST', '/_test/reset', { raw: '[1]' }), 400, 'malformed_request');
    const me = await ada.get('/me');
    assert.equal(me.status, 200, 'the old token still works after rejected resets');
    assert.equal(me.body.balance, 10_000);
  });

  it('replaces all state: old users and tokens are gone, the new fixture is visible', async () => {
    const ada = await login(port, 'ada');
    await reset(port, fixture({ currency: 'JPY', minor_units: 0, users: [user('dee', 7)] }));
    expectError(await ada.get('/me'), 401, 'unauthenticated');
    expectError(await request(port, 'POST', '/auth/login', { json: { email: 'ada@example.com', password: PASSWORD } }),
      401, 'unauthenticated');
    const dee = await login(port, 'dee');
    const me = await dee.get('/me');
    assert.deepEqual(me.body, {
      user_id: 'u_dee', display_name: 'Dee', handle: 'dee', balance: 7, total: 7, available: 7, held: 0,
      currency: 'JPY', minor_units: 0,
    });
  });

  it('ignores unknown fields and accepts optional collections', async () => {
    const reply = await request(port, 'POST', '/_test/reset', {
      json: { currency: 'BHD', minor_units: 3, users: [user('ada', 0, { colour: 'blue' })], extra: true },
    });
    assert.equal(reply.status, 204);
    assert.equal(reply.text, '');
  });

  it('keeps a fixture payment settlement_id and defaults it to null (D34)', async () => {
    await reset(port, fixture({
      payments: [
        { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 5, settlement_id: 'st_seed' },
        { id: 'p_2', from_user_id: 'u_bob', to_user_id: 'u_ada', amount: 6, settlement_id: null },
        { id: 'p_3', from_user_id: 'u_bob', to_user_id: 'u_cy', amount: 7 },
      ],
    }));
    expectError(await request(port, 'POST', '/_test/reset', {
      json: fixture({ payments: [{ id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 5, settlement_id: 7 }] }),
    }), 422, 'validation_failed');
    const feed = (await (await login(port, 'cy')).get('/activity')).body.payments;
    assert.deepEqual(feed.map((p: any) => [p.payment_id, p.settlement_id]), [['p_3', null], ['p_2', null], ['p_1', 'st_seed']]);
  });

  it('ignores the Authorization header', async () => {
    const reply = await request(port, 'POST', '/_test/reset', { json: fixture(), headers: { authorization: 'Bearer junk' } });
    assert.equal(reply.status, 204);
  });
});

describe('signup and login', () => {
  it('creates an account with a derived handle and a zero balance', async () => {
    const reply = await signup('Dee.Ann+tag@example.com', PASSWORD, 'Dee');
    assert.equal(reply.status, 201);
    assert.deepEqual(Object.keys(reply.body).sort(), ['display_name', 'token', 'user_id']);
    assert.equal(reply.body.display_name, 'Dee');
    const me = await new Client(port, reply.body.token).get('/me');
    assert.equal(me.body.handle, 'dee_ann_tag');
    assert.equal(me.body.balance, 0);
    assert.equal(me.body.user_id, reply.body.user_id);
    assert.ok(reply.body.user_id.length <= 64);
  });

  it('derives handles by code point: truncation, upper case, non-ASCII', async () => {
    const cases: Array<[string, string]> = [
      [`${'a'.repeat(30)}@example.com`, 'a'.repeat(20)],
      ['MiXeD@example.com', 'mixed'],
      ['jürgen.ø@example.com', 'j_rgen__'],
      ['😀😀x@example.com', '__x'],
    ];
    for (const [email, handle] of cases) {
      const reply = await signup(email);
      assert.equal(reply.status, 201, reply.text);
      const me = await new Client(port, reply.body.token).get('/me');
      assert.equal(me.body.handle, handle, email);
    }
  });

  it('refuses a taken email case-insensitively and a taken derived handle without creating an account', async () => {
    expectError(await signup('ADA@Example.com'), 409, 'email_taken');
    expectError(await signup('ada@other.example'), 409, 'handle_taken');
    expectError(await request(port, 'POST', '/auth/login', { json: { email: 'ada@other.example', password: PASSWORD } }),
      401, 'unauthenticated');
  });

  it('validates types (400), presence and values (422)', async () => {
    const post = (json: unknown) => request(port, 'POST', '/auth/signup', { json });
    expectError(await post({ email: 5, password: PASSWORD, display_name: 'X' }), 400, 'malformed_request');
    expectError(await post({ email: 'x@example.com', password: null, display_name: 'X' }), 400, 'malformed_request');
    expectError(await post({ email: 'x@example.com', password: PASSWORD, display_name: ['X'] }), 400, 'malformed_request');
    expectError(await post({ email: 'x@example.com', password: PASSWORD }), 422, 'validation_failed');
    expectError(await post({ password: PASSWORD, display_name: 'X' }), 422, 'validation_failed');
    for (const email of ['plain', '@example.com', 'x@', 'a@b@c', 'a b@example.com', `${'a'.repeat(250)}@example.com`]) {
      expectError(await signup(email), 422, 'validation_failed');
    }
    expectError(await signup('x@example.com', '1234567'), 422, 'validation_failed');
    expectError(await signup('x@example.com', 'p'.repeat(1025)), 422, 'validation_failed');
    expectError(await signup('x@example.com', PASSWORD, ''), 422, 'validation_failed');
    expectError(await signup('x@example.com', PASSWORD, 'n'.repeat(101)), 422, 'validation_failed');
    assert.equal((await signup('x@example.com', '😀'.repeat(8), 'n'.repeat(100))).status, 201);
  });

  it('logs in seeded and new users, with several valid tokens per account', async () => {
    const first = await login(port, 'ada');
    const second = await login(port, 'ada');
    assert.notEqual(first.token, second.token);
    assert.equal((await first.get('/me')).status, 200);
    assert.equal((await second.get('/me')).status, 200);
    const caseless = await request(port, 'POST', '/auth/login', { json: { email: 'Ada@EXAMPLE.com', password: PASSWORD } });
    assert.equal(caseless.status, 200);
    assert.deepEqual(Object.keys(caseless.body).sort(), ['display_name', 'token', 'user_id']);
    await signup('dee@example.com');
    assert.equal((await login(port, 'dee')).token.length > 40, true);
  });

  it('refuses wrong passwords and unknown emails with 401, bad input with 400 or 422', async () => {
    const post = (json: unknown) => request(port, 'POST', '/auth/login', { json });
    expectError(await post({ email: 'ada@example.com', password: 'wrong horse' }), 401, 'unauthenticated');
    expectError(await post({ email: 'ada@example.com', password: 'x' }), 401, 'unauthenticated');
    expectError(await post({ email: 'nobody@example.com', password: PASSWORD }), 401, 'unauthenticated');
    expectError(await post({ email: 'ada@example.com' }), 422, 'validation_failed');
    expectError(await post({ email: 'not-an-email', password: PASSWORD }), 422, 'validation_failed');
    expectError(await post({ email: 'ada@example.com', password: 12345678 }), 400, 'malformed_request');
  });
});

describe('authentication on GET /me', () => {
  it('rejects a missing header, another scheme, an empty token and an unknown token', async () => {
    const ada = await login(port, 'ada');
    const headers = [
      undefined, `Basic ${ada.token}`, 'Bearer', 'Bearer ', `Token ${ada.token}`, 'Bearer unknown-token',
      `Bearer ${ada.token} extra`, `${ada.token}`,
    ];
    for (const authorization of headers) {
      const reply = await request(port, 'GET', '/me', authorization === undefined ? {} : { headers: { authorization } });
      expectError(reply, 401, 'unauthenticated');
    }
  });

  it('accepts any case of the scheme and several spaces', async () => {
    const ada = await login(port, 'ada');
    for (const authorization of [`bearer ${ada.token}`, `BEARER   ${ada.token}`]) {
      const reply = await request(port, 'GET', '/me', { headers: { authorization } });
      assert.equal(reply.status, 200);
    }
  });

  it('exempt endpoints ignore an invalid Authorization header', async () => {
    const headers = { authorization: 'Bearer junk' };
    assert.equal((await request(port, 'GET', '/health', { headers })).status, 200);
    assert.equal((await request(port, 'POST', '/auth/login',
      { headers, json: { email: 'ada@example.com', password: PASSWORD } })).status, 200);
    assert.equal((await request(port, 'POST', '/auth/signup',
      { headers, json: { email: 'eve@example.com', password: PASSWORD, display_name: 'Eve' } })).status, 201);
  });

  it('returns exactly the Me fields', async () => {
    const reply = await (await login(port, 'bob')).get('/me');
    assert.deepEqual(reply.body, {
      user_id: 'u_bob', display_name: 'Bob', handle: 'bob', balance: 2500, total: 2500, available: 2500, held: 0,
      currency: 'EUR', minor_units: 2,
    });
  });
});

describe('concurrency', () => {
  it('50 concurrent logins all succeed', async () => {
    const replies = await Promise.all(Array.from({ length: 50 }, () =>
      request(port, 'POST', '/auth/login', { json: { email: 'ada@example.com', password: PASSWORD } })));
    assert.deepEqual(replies.map((r) => r.status), Array(50).fill(200));
  });

  it('10 concurrent signups with one email give one 201 and nine email_taken', async () => {
    const replies = await Promise.all(Array.from({ length: 10 }, () => signup('dup@example.com')));
    const statuses = replies.map((r) => r.status).sort();
    assert.deepEqual(statuses, [201, ...Array(9).fill(409)]);
    for (const r of replies.filter((x) => x.status === 409)) expectError(r, 409, 'email_taken');
  });

  it('concurrent signups deriving one handle give one 201 and handle_taken for the rest', async () => {
    const replies = await Promise.all(Array.from({ length: 10 }, (_, i) => signup(`same@domain${i}.example`)));
    const statuses = replies.map((r) => r.status).sort();
    assert.deepEqual(statuses, [201, ...Array(9).fill(409)]);
    for (const r of replies.filter((x) => x.status === 409)) expectError(r, 409, 'handle_taken');
  });
});
