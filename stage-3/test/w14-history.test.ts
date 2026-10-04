// W14: instants, seeded times, revision 1, opening balances, GET /me as of an instant and as
// known at an instant, historical holds and closed_at.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, describe, it } from 'node:test';
import { selectRevision } from '../src/history.ts';
import { instantKey, msKey } from '../src/instant.ts';
import { store, type Payment } from '../src/state.ts';
import { Client, expectError, fixture, login, request, reset, type Server, startServer } from './helpers.ts';

let server: Server;
let port: number;

before(async () => {
  server = await startServer();
  port = server.port;
});
after(() => server.close());

const key = () => randomUUID();
const TS_RE = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$/;
const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString().replace('Z', '+00:00');
// An issued timestamp moved by whole milliseconds, and the instant one microsecond before it.
const shift = (ts: string, ms: number) => new Date(Date.parse(ts) + ms).toISOString();
const microBefore = (ts: string) => shift(ts, -1).replace('Z', '999Z');
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const SEEDED_TOTAL = 10_000 + 2_500 + 500;

const q = (name: string, value: string) => `${name}=${encodeURIComponent(value)}`;
async function meAt(c: Client, params: Record<string, string>) {
  const query = Object.entries(params).map(([n, v]) => q(n, v)).join('&');
  const reply = await c.get(`/me?${query}`);
  assert.equal(reply.status, 200, reply.text);
  return reply.body;
}
const money = (m: any) => [m.total, m.held, m.available];

describe('instants (plan 3.4, W14.4)', () => {
  it('accepts the RFC 3339 forms with an offset, of at most 64 characters', () => {
    for (const text of [
      '2026-01-01T00:00:00Z', '2026-01-01t00:00:00z', '2026-01-01T00:00:00+05:30', '2026-01-01T00:00:00-00:00',
      '2026-01-01T00:00:00.5Z', '2026-01-01T00:00:00.123456789012Z', '2024-02-29T23:59:59Z', '2000-02-29T00:00:00Z',
      '0000-01-01T00:00:00+23:59', '9999-12-31T23:59:59.999999-23:59', `2026-01-01T00:00:00.${'1'.repeat(43)}Z`,
    ]) assert.notEqual(instantKey(text), null, text);
    assert.equal(`2026-01-01T00:00:00.${'1'.repeat(43)}Z`.length, 64);
  });

  it('refuses everything else', () => {
    for (const text of [
      '', '2026-01-01', '2026-01-01T00:00:00', '2026-01-01 00:00:00Z', '2026-02-30T00:00:00Z', '2023-02-29T00:00:00Z',
      '1900-02-29T00:00:00Z', '2026-13-01T00:00:00Z', '2026-00-10T00:00:00Z', '2026-01-00T00:00:00Z',
      '2026-01-01T24:00:00Z', '2026-01-01T00:60:00Z', '2026-01-01T00:00:60Z', '2026-01-01T00:00:00+24:00',
      '2026-01-01T00:00:00+05:60', '2026-01-01T00:00:00+0530', '2026-01-01T00:00:00.Z', '2026-1-01T00:00:00Z',
      ' 2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z ', '+2026-01-01T00:00:00Z', '２０２６-01-01T00:00:00Z',
      `2026-01-01T00:00:00.${'1'.repeat(44)}Z`, 20260101, null,
    ]) assert.equal(instantKey(text), null, String(text));
  });

  it('compares exactly: equal instants in any form are equal, a microsecond apart are not', () => {
    const k = (t: string) => instantKey(t) as string;
    assert.equal(k('2026-01-01T00:00:00Z'), k('2026-01-01T05:30:00+05:30'));
    assert.equal(k('2026-01-01T00:00:00Z'), k('2025-12-31T23:00:00-01:00'));
    assert.equal(k('2026-01-01T00:00:00.5Z'), k('2026-01-01T00:00:00.500000z'));
    assert.equal(k('2026-01-01T00:00:00Z'), k('2026-01-01T00:00:00.000Z'));
    assert.ok(k('2026-01-01T00:00:00.000001Z') > k('2026-01-01T00:00:00Z'));
    assert.ok(k('2026-01-01T00:00:00.000000000001Z') > k('2026-01-01T00:00:00Z'));
    assert.ok(k('2026-01-01T00:00:00.9999999999Z') < k('2026-01-01T00:00:01Z'));
    assert.ok(k('0099-12-31T23:59:59Z') < k('0100-01-01T00:00:00Z'));
    assert.ok(k('0000-01-01T00:00:00+23:59') < k('0000-01-01T00:00:00Z'));
    assert.ok(k('9999-12-31T23:59:59-23:59') > k('9999-12-31T23:59:59Z'));
    for (const ms of [0, 1, 999, 1_000, Date.parse('2026-10-04T12:34:56.789Z')]) {
      assert.equal(msKey(ms), k(new Date(ms).toISOString()), String(ms));
    }
  });
});

describe('revision selection (plan 3.7)', () => {
  it('takes the highest revision recorded by K and by the sequence cutoff', () => {
    const rev = (revision: number, recordedAt: string, seq: number) => ({
      revision, amount: revision * 100, effectiveAt: recordedAt, effKey: instantKey(recordedAt) as string,
      recordedAt, recKey: instantKey(recordedAt) as string, reason: '', seq,
    });
    const p = { revisions: [rev(1, '2026-01-01T00:00:00Z', 5), rev(2, '2026-01-02T00:00:00Z', 9), rev(3, '2026-01-03T00:00:00Z', 12)] } as Payment;
    const pick = (K: string | null, C: number) => selectRevision(p, { K: K === null ? null : instantKey(K), C })?.revision ?? null;
    assert.equal(pick(null, 100), 3);
    assert.equal(pick(null, 11), 2);
    assert.equal(pick(null, 9), 2);
    assert.equal(pick(null, 4), null);
    assert.equal(pick('2026-01-02T00:00:00Z', 100), 2, 'inclusive at K');
    assert.equal(pick('2026-01-01T23:59:59.999999Z', 100), 1);
    assert.equal(pick('2025-12-31T23:59:59Z', 100), null);
    assert.equal(pick('2026-01-03T00:00:00Z', 10), 2, 'the cutoff and K together');
  });
});

describe('seeded created_at (W14.1)', () => {
  const PAST = '2020-06-01T12:00:00.123456+05:30';

  it('is returned exactly as written; omitted, it is the reset time; the feed orders by instant', async () => {
    await reset(port, fixture({
      payments: [
        { id: 'p_plain', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 10 },
        { id: 'p_old', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1_000, created_at: PAST },
        { id: 'p_older', from_user_id: 'u_bob', to_user_id: 'u_ada', amount: 5, created_at: '2019-01-01T00:00:00z' },
      ],
      authorizations: [
        { id: 'a_old', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 50, expires_at: inHours(2), created_at: '2021-03-04t05:06:07-08:00' },
        { id: 'a_plain', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 60, expires_at: inHours(2) },
      ],
    }));
    const [ada, bob] = await Promise.all(['ada', 'bob'].map((h) => login(port, h)));
    const one = await ada.post('/payments', { json: { to_handle: 'bob', amount: 1 }, key: key() });
    const two = await ada.post('/payments', { json: { to_handle: 'bob', amount: 2 }, key: key() });
    assert.ok(two.body.created_at > one.body.created_at, 'two writes in a row never share a time');
    const feed = (await bob.get('/activity')).body.payments;
    assert.deepEqual(feed.map((p: any) => p.payment_id), [two.body.payment_id, one.body.payment_id, 'p_plain', 'p_old', 'p_older']);
    const plain = feed[2].created_at;
    assert.match(plain, TS_RE);
    assert.ok(plain < one.body.created_at);
    assert.deepEqual(feed.slice(3).map((p: any) => p.created_at), [PAST, '2019-01-01T00:00:00z']);
    const holds = (await ada.get('/authorizations')).body.authorizations;
    assert.deepEqual(holds.map((a: any) => [a.authorization_id, a.created_at]), [['a_plain', plain], ['a_old', '2021-03-04t05:06:07-08:00']]);
  });

  it('keeps fixture order for equal instants', async () => {
    await reset(port, fixture({
      payments: [
        { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1, created_at: '2020-01-01T00:00:00Z' },
        { id: 'p_2', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 2, created_at: '2020-01-01T01:00:00+01:00' },
        { id: 'p_3', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 3, created_at: '2020-01-01T00:00:00.000Z' },
      ],
    }));
    const ada = await login(port, 'ada');
    assert.deepEqual((await ada.get('/activity')).body.payments.map((p: any) => p.payment_id), ['p_3', 'p_2', 'p_1']);
  });

  it('is 422 when later than the reset, invalid or null, and nothing changes', async () => {
    await reset(port, fixture());
    const ada = await login(port, 'ada');
    await ada.post('/payments', { json: { to_handle: 'bob', amount: 7 }, key: key() });
    const before = (await request(port, 'GET', '/_test/export')).body;
    const late = new Date(Date.now() + 60_000).toISOString();
    for (const created_at of [late, '9999-01-01T00:00:00Z', '2020-01-01', '2020-01-01T00:00:00', '2020-02-30T00:00:00Z', '', null, 5]) {
      for (const shape of [
        { payments: [{ id: 'p_x', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1, created_at }] },
        { authorizations: [{ id: 'a_x', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1, expires_at: inHours(1), created_at }] },
      ]) {
        expectError(await request(port, 'POST', '/_test/reset', { json: fixture(shape) }), 422, 'validation_failed');
      }
    }
    assert.deepEqual((await request(port, 'GET', '/_test/export')).body, before);
  });
});

describe('revision 1 and opening balances (W14.2, W14.3)', () => {
  it('gives every payment revision 1 at its created_at', async () => {
    await reset(port, fixture({
      settlement_operator_ids: ['u_ada'],
      payments: [{ id: 'p_seed', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 30, created_at: '2020-01-01T00:00:00+02:00' }],
    }));
    const [ada, bob] = await Promise.all(['ada', 'bob'].map((h) => login(port, h)));
    await ada.post('/payments', { json: { to_handle: 'bob', amount: 11 }, key: key() });
    const req = (await bob.post('/requests', { json: { payer_handle: 'ada', amount: 12 }, key: key() })).body;
    await ada.post(`/requests/${req.request_id}/pay`, { json: {}, key: key() });
    const settled = (await ada.post('/settlements', {
      json: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 13 }, { from_handle: 'bob', to_handle: 'cy', amount: 14 }] },
      key: key(),
    })).body;
    const hold = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 100 }, key: key() })).body;
    await bob.post(`/authorizations/${hold.authorization_id}/capture`, { json: { amount: 15, final: false }, key: key() });
    const payments = store.state.payments;
    assert.equal(payments.length, 6);
    for (const p of payments) {
      assert.equal(p.revisions.length, 1, p.id);
      const [r] = p.revisions;
      assert.deepEqual([r.revision, r.amount, r.effectiveAt, r.recordedAt, r.reason, r.seq], [1, p.amount, p.createdAt, p.createdAt, '', p.seq]);
    }
    for (const member of settled.payments) assert.equal(member.created_at, settled.committed_at);
  });

  it('starts each seeded user at balance minus their seeded payments, and a signup at 0', async () => {
    await reset(port, fixture({
      payments: [
        { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1_000, created_at: '2020-01-01T00:00:00Z' },
        { id: 'p_2', from_user_id: 'u_bob', to_user_id: 'u_cy', amount: 300, created_at: '2020-02-01T00:00:00Z' },
      ],
    }));
    const [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(port, h)));
    const early = { as_of: '2019-12-31T23:59:59.999999Z' };
    assert.deepEqual(await Promise.all([ada, bob, cy].map(async (c) => (await meAt(c, early)).total)), [11_000, 1_800, 200]);
    assert.deepEqual(await Promise.all([ada, bob, cy].map(async (c) => (await c.get('/me')).body.total)), [10_000, 2_500, 500]);
    const signup = await request(port, 'POST', '/auth/signup', { json: { email: 'dee@example.com', password: 'correct horse', display_name: 'Dee' } });
    assert.equal(signup.status, 201, signup.text);
    const dee = new Client(port, signup.body.token);
    const { handle } = (await dee.get('/me')).body;
    const paid = (await ada.post('/payments', { json: { to_handle: handle, amount: 40 }, key: key() })).body;
    assert.equal((await meAt(dee, { as_of: microBefore(paid.created_at) })).total, 0);
    assert.equal((await meAt(dee, { as_of: paid.created_at })).total, 40);
  });
});

describe('GET /me as of an instant (W14.4)', () => {
  const AT = '2020-06-01T12:00:00.123456+05:30';
  let ada: Client;

  before(async () => {
    await reset(port, fixture({ payments: [{ id: 'p_at', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1_000, created_at: AT }] }));
    ada = await login(port, 'ada');
  });

  it('is inclusive at exactly the payment time and excludes it a microsecond earlier', async () => {
    assert.equal((await meAt(ada, { as_of: AT })).total, 10_000);
    assert.equal((await meAt(ada, { as_of: '2020-06-01T06:30:00.123456Z' })).total, 10_000, 'the same instant in UTC');
    assert.equal((await meAt(ada, { as_of: '2020-06-01T06:30:00.1234560000Z' })).total, 10_000);
    assert.equal((await meAt(ada, { as_of: '2020-06-01T12:00:00.123455+05:30' })).total, 11_000);
    assert.equal((await meAt(ada, { as_of: '2020-06-01T06:30:00.1234559999999Z' })).total, 11_000);
    assert.deepEqual(money(await meAt(ada, { as_of: '9999-12-31T23:59:59Z' })), money((await ada.get('/me')).body));
  });

  it('echoes as_of exactly as sent; a + sent raw or as %2B is a plus sign', async () => {
    for (const asOf of ['2020-06-01T00:00:00Z', '2020-06-01t00:00:00z', '2020-06-01T00:00:00-00:00', '2020-06-01T05:30:00.10000+05:30', `2020-06-01T00:00:00.${'0'.repeat(40)}1Z`]) {
      const body = await meAt(ada, { as_of: asOf });
      assert.equal(body.as_of, asOf);
      assert.equal('known_at' in body, false);
    }
    const raw = await ada.get(`/me?as_of=${AT}`);
    const encoded = await ada.get(`/me?as_of=${AT.replace('+', '%2B')}`);
    assert.equal(raw.status, 200, raw.text);
    assert.deepEqual(raw.body, encoded.body);
    assert.equal(raw.body.as_of, AT);
    assert.equal(raw.body.total, 10_000);
  });

  it('keeps the stage-2 body without parameters, and takes the first of repeated parameters', async () => {
    const plain = (await ada.get('/me')).body;
    assert.deepEqual(Object.keys(plain).sort(), ['available', 'balance', 'currency', 'display_name', 'handle', 'held', 'minor_units', 'total', 'user_id']);
    const first = await ada.get(`/me?as_of=2019-01-01T00:00:00Z&as_of=bad&limit=x`);
    assert.equal(first.status, 200, first.text);
    assert.deepEqual([first.body.as_of, first.body.total], ['2019-01-01T00:00:00Z', 11_000]);
    expectError(await ada.get('/me?as_of=bad&as_of=2019-01-01T00:00:00Z'), 422, 'validation_failed');
  });

  it('refuses an invalid as_of with 422', async () => {
    for (const asOf of ['', '2020-06-01', '2020-06-01T00:00:00', '2020-02-30T00:00:00Z', '2020-06-01T24:00:00Z',
      '2020-06-01T00:00:60Z', '2020-06-01T00:00:00+24:00', `2020-06-01T00:00:00.${'1'.repeat(44)}Z`, '2020-06-01T00:00:00 05:30']) {
      expectError(await ada.get(`/me?${q('as_of', asOf)}`), 422, 'validation_failed');
    }
    expectError(await ada.get('/me?as_of'), 422, 'validation_failed');
    expectError(await ada.get('/me?as_of=%E0%A4%A'), 422, 'validation_failed');
    expectError(await ada.get('/me?known_at=2020-06-01'), 422, 'validation_failed');
    expectError(await request(port, 'GET', '/me?as_of=2020-06-01T00:00:00Z'), 401, 'unauthenticated');
  });
});

describe('GET /me as known at an instant (W14.5)', () => {
  it('leaves out payments recorded and holds created after K, and echoes known_at', async () => {
    await reset(port, fixture({ payments: [{ id: 'p_seed', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1_000, created_at: '2020-01-01T00:00:00Z' }] }));
    const ada = await login(port, 'ada');
    const paid = (await ada.post('/payments', { json: { to_handle: 'bob', amount: 100 }, key: key() })).body;
    const hold = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 300 }, key: key() })).body;
    const now = money((await ada.get('/me')).body);
    assert.deepEqual(now, [9_900, 300, 9_600]);
    assert.deepEqual(money(await meAt(ada, { known_at: microBefore(hold.created_at) })), [9_900, 0, 9_900]);
    assert.deepEqual(money(await meAt(ada, { known_at: hold.created_at })), now);
    assert.deepEqual(money(await meAt(ada, { known_at: microBefore(paid.created_at) })), [10_000, 0, 10_000]);
    assert.deepEqual(money(await meAt(ada, { known_at: '2019-12-31T23:59:59Z' })), [11_000, 0, 11_000]);
    const future = await meAt(ada, { known_at: '9999-12-31T23:59:59.999+00:00' });
    assert.deepEqual(money(future), now);
    assert.deepEqual([future.known_at, 'as_of' in future], ['9999-12-31T23:59:59.999+00:00', false]);
    const both = await meAt(ada, { as_of: '2020-01-01T00:00:00Z', known_at: microBefore(paid.created_at) });
    assert.deepEqual([...money(both), both.as_of, both.known_at], [10_000, 0, 10_000, '2020-01-01T00:00:00Z', microBefore(paid.created_at)]);
    assert.equal(both.balance, both.total);
  });
});

describe('historical holds and closed_at (W14.6, W14.7)', () => {
  it('follows each hold through creation, captures, void and expiry', async () => {
    await reset(port, fixture({
      authorization_ttl_seconds: 3600,
      authorizations: [
        { id: 'a_seed_open', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 400, expires_at: inHours(2), created_at: '2020-06-01T00:00:00Z' },
        { id: 'a_seed_reset', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 40, expires_at: inHours(2) },
        { id: 'a_seed_captured', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 900, status: 'captured', captured_amount: 900, expires_at: inHours(2), created_at: '2020-06-01T00:00:00Z' },
        { id: 'a_seed_voided', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 800, status: 'voided', expires_at: inHours(2), created_at: '2020-06-01T00:00:00Z' },
        { id: 'a_seed_expired', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 700, status: 'expired', expires_at: inHours(-2), created_at: '2020-06-01T00:00:00Z' },
        { id: 'a_lapsed', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 600, expires_at: '2020-07-01T00:00:00.5+01:00', created_at: '2020-06-01T00:00:00Z' },
      ],
    }));
    const [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(port, h)));
    const seededAt = Object.fromEntries((await ada.get('/authorizations')).body.authorizations.map((a: any) => [a.authorization_id, a]));
    const reset2 = seededAt.a_seed_reset.created_at;
    assert.match(reset2, TS_RE);

    // Seeded holds: the open ones count from their created_at (else the reset); the closed ones never.
    assert.equal((await meAt(ada, { as_of: '2020-05-31T23:59:59.999999Z' })).held, 0);
    assert.equal((await meAt(ada, { as_of: '2020-06-01T00:00:00Z' })).held, 1_000, 'a_seed_open and a_lapsed, no closed seed');
    assert.equal((await meAt(ada, { as_of: '2020-06-30T23:00:00.4999Z' })).held, 1_000);
    assert.equal((await meAt(ada, { as_of: '2020-06-30T23:00:00.5Z' })).held, 400, 'a_lapsed expired at its deadline');
    assert.equal((await meAt(ada, { as_of: microBefore(reset2) })).held, 400);
    assert.equal((await meAt(ada, { as_of: reset2 })).held, 440);
    assert.equal((await meAt(ada, { as_of: inHours(3) })).held, 0, 'beyond the deadline of a still-open hold');
    assert.deepEqual(
      Object.fromEntries(Object.values(seededAt).map((a: any) => [a.authorization_id, [a.status, a.closed_at]])),
      {
        a_seed_open: ['open', null], a_seed_reset: ['open', null], a_seed_captured: ['captured', reset2],
        a_seed_voided: ['voided', reset2], a_seed_expired: ['expired', reset2], a_lapsed: ['expired', '2020-07-01T00:00:00.5+01:00'],
      },
    );

    const post = (k: string, amount: number) => ada.post('/authorizations', { json: { to_handle: 'bob', amount }, key: k });
    const capture = (id: string, json: unknown) => bob.post(`/authorizations/${id}/capture`, { json, key: key() });
    const partial = (await post(key(), 1_000)).body;
    const cap1 = (await capture(partial.authorization_id, { amount: 300, final: false })).body;
    const finalHold = (await post(key(), 500)).body;
    const cap2 = (await capture(finalHold.authorization_id, { amount: 100, final: true })).body;
    const wholeHold = (await post(key(), 250)).body;
    const cap3 = (await capture(wholeHold.authorization_id, { amount: 250, final: false })).body;
    const voidHold = (await post(key(), 200)).body;
    const voided = (await ada.post(`/authorizations/${voidHold.authorization_id}/void`)).body;
    const shortHold = (await post(key(), 70)).body;
    const shortExpiry = shortHold.expires_at;

    const base = 440; // the two seeded open holds, from the reset until their deadlines
    const steps: [string, number, number][] = [
      [microBefore(partial.created_at), 10_000, base],
      [partial.created_at, 10_000, base + 1_000],
      [microBefore(cap1.created_at), 10_000, base + 1_000],
      [cap1.created_at, 9_700, base + 700],
      [finalHold.created_at, 9_700, base + 700 + 500],
      [cap2.created_at, 9_600, base + 700],
      [wholeHold.created_at, 9_600, base + 700 + 250],
      [cap3.created_at, 9_350, base + 700],
      [voidHold.created_at, 9_350, base + 900],
      [microBefore(voided.closed_at), 9_350, base + 900],
      [voided.closed_at, 9_350, base + 700],
      [shortHold.created_at, 9_350, base + 770],
    ];
    for (const [asOf, total, held] of steps) {
      const views = await Promise.all([ada, bob, cy].map((c) => meAt(c, { as_of: asOf })));
      assert.deepEqual([views[0].total, views[0].held], [total, held], asOf);
      for (const m of views) {
        assert.equal(m.balance, m.total);
        assert.equal(m.available, m.total - m.held);
      }
      assert.equal(views.reduce((sum, m) => sum + m.total, 0), SEEDED_TOTAL, `the sum at ${asOf}`);
    }
    // A capture known after K does not count, so the hold it reduced still holds in full.
    assert.equal((await meAt(ada, { known_at: microBefore(cap1.created_at) })).held, base + 1_000);
    // A void known after K: the voided hold still holds.
    assert.equal((await meAt(ada, { known_at: microBefore(voided.closed_at) })).held, base + 700 + 200 + 0);
    assert.equal((await meAt(ada, { as_of: shortExpiry })).held, base, 'every API hold is past its deadline, the seeded ones are not');

    const closed = Object.fromEntries((await ada.get('/authorizations?limit=50')).body.authorizations
      .map((a: any) => [a.authorization_id, [a.status, a.closed_at]]));
    assert.deepEqual(closed[partial.authorization_id], ['open', null], 'a nonfinal capture leaves it open');
    assert.deepEqual(closed[finalHold.authorization_id], ['captured', cap2.created_at]);
    assert.deepEqual(closed[wholeHold.authorization_id], ['captured', cap3.created_at]);
    assert.deepEqual(closed[voidHold.authorization_id], ['voided', voided.closed_at]);
    assert.match(voided.closed_at, TS_RE);
    assert.ok(voided.closed_at > voidHold.created_at);
    assert.equal(partial.closed_at, null);
  });

  it('shows an expired-by-clock hold closed at its expires_at, exactly as stored', async () => {
    await reset(port, fixture({ authorization_ttl_seconds: 1 }));
    const ada = await login(port, 'ada');
    const hold = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 10 }, key: key() })).body;
    assert.equal(hold.closed_at, null);
    await sleep(1_100);
    const [listed] = (await ada.get('/authorizations')).body.authorizations;
    assert.deepEqual([listed.status, listed.closed_at], ['expired', hold.expires_at]);
    assert.deepEqual(money(await meAt(ada, { as_of: shift(hold.expires_at, -1) })), [10_000, 10, 9_990]);
    assert.deepEqual(money(await meAt(ada, { as_of: hold.expires_at })), [10_000, 0, 10_000]);
  });

  it('counts a seeded open hold\'s seeded captures at their times', async () => {
    await reset(port, fixture({
      payments: [{ id: 'p_cap', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 150, authorization_id: 'a_part', created_at: '2020-06-02T00:00:00Z' }],
      authorizations: [
        { id: 'a_part', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, captured_amount: 200, payment_ids: ['p_cap'], expires_at: inHours(2), created_at: '2020-06-01T00:00:00Z' },
      ],
    }));
    const ada = await login(port, 'ada');
    assert.deepEqual(money((await ada.get('/me')).body), [10_000, 300, 9_700]);
    // 50 of the captured 200 has no seeded payment, so it counts from the hold's creation.
    assert.deepEqual(money(await meAt(ada, { as_of: '2020-06-01T00:00:00Z' })), [10_150, 450, 9_700]);
    assert.deepEqual(money(await meAt(ada, { as_of: '2020-06-02T00:00:00Z' })), [10_000, 300, 9_700]);
  });
});
