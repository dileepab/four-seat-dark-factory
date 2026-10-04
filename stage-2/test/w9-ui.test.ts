// W9: the UI foundation. The browser's pure modules (W9.5) and the HTML routes, headers and
// static files (W9.1). The browser behaviour itself is exercised by the acceptance suite.

import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import { after, before, describe, it } from 'node:test';
import { equalShares as serverShares } from '../src/handlers/splits.ts';
import { acceptsHtml, CSP } from '../src/ui.ts';
// @ts-expect-error plain browser JavaScript modules
import { decimalText, formatMoney, parseAmount } from '../ui/assets/money.js';
// @ts-expect-error plain browser JavaScript modules
import { newKey, RetryIdentity } from '../ui/assets/retry.js';
// @ts-expect-error plain browser JavaScript modules
import { cleanHandle, equalShares, parseHandles } from '../ui/assets/split.js';
import { fixture, login, request, reset, startServer, type Server } from './helpers.ts';

describe('amounts in the browser (W9.5, I39, I40, D44)', () => {
  it('formats integer minor units exactly for minor_units 0, 2 and 3', () => {
    const cases: [number, number, string][] = [
      [10_000, 2, '100.00 EUR'], [1, 2, '0.01 EUR'], [0, 2, '0.00 EUR'], [1550, 2, '15.50 EUR'],
      [1200, 0, '1200 JPY'], [0, 0, '0 JPY'], [1, 3, '0.001 KWD'], [1500, 3, '1.500 KWD'],
      [2 ** 53, 2, '90071992547409.92 EUR'], [1_000_000_000, 3, '1000000.000 KWD'],
    ];
    for (const [minor, units, text] of cases) {
      const currency = text.slice(-3);
      assert.equal(formatMoney(minor, units, currency), text);
    }
    assert.equal(decimalText(2000, 2), '20.00');
    assert.equal(decimalText(2000, 0), '2000');
    assert.equal(decimalText(5, 3), '0.005');
  });

  it('parses the D44 grammar into exact minor units', () => {
    const good: [string, number, number][] = [
      ['15', 2, 1500], ['15.00', 2, 1500], ['15.5', 2, 1550], [' 15.05 ', 2, 1505], ['0.01', 2, 1], ['007', 2, 700],
      ['10000000', 2, 1_000_000_000], ['15', 0, 15], ['1000000000', 0, 1_000_000_000], ['15', 3, 15_000],
      ['15.005', 3, 15_005], ['15.5', 3, 15_500], ['0.001', 3, 1], ['1000000', 3, 1_000_000_000],
      ['0.29', 2, 29], ['1.15', 2, 115], ['4.35', 2, 435], ['99999.99', 2, 9_999_999],
    ];
    for (const [text, units, value] of good) assert.deepEqual(parseAmount(text, units), { value }, `${text} @${units}`);
    const bad: [string, number][] = [
      ['', 2], ['   ', 2], ['abc', 2], ['15.005', 2], ['1e3', 2], ['-1', 2], ['+1', 2], ['1,5', 2], ['1 000', 2],
      ['0', 2], ['0.00', 2], ['10000000.01', 2], ['15.', 2], ['.5', 2], ['15.5', 0], ['15.', 0], ['0', 0],
      ['1000000001', 0], ['15.0005', 3], ['１５', 2], ['Infinity', 2], ['0x10', 2], ['1_000', 2],
    ];
    for (const [text, units] of bad) {
      const result = parseAmount(text, units);
      assert.ok(typeof result.error === 'string' && result.error.length > 10 && result.value === undefined, `${text} @${units}`);
    }
  });
});

describe('the split preview (W9.5)', () => {
  it('matches the server rule for every amount and size tried', () => {
    for (const n of [1, 2, 3, 7, 13, 200]) {
      for (const amount of [1, 2, 10, 99, 100, 1000, 1001, 999_999_999, 1_000_000_000]) {
        assert.deepEqual(equalShares(amount, n), serverShares(amount, n), `${amount} among ${n}`);
      }
    }
    assert.deepEqual(equalShares(1000, 3), [334, 333, 333]);
  });

  it('reads handles: trimmed, one @ removed, empty entries dropped, repeats and over 200 refused', () => {
    assert.equal(cleanHandle('  @bob '), 'bob');
    assert.equal(cleanHandle('@@bob'), '@bob');
    assert.deepEqual(parseHandles('ada, @bob,,cy ,'), { handles: ['ada', 'bob', 'cy'] });
    assert.deepEqual(parseHandles('cy,bob,ada').handles, ['cy', 'bob', 'ada']);
    for (const text of ['', ' , ', 'ada,bob,@ada', Array.from({ length: 201 }, (_, i) => `u${i}`).join(',')]) {
      assert.equal(typeof parseHandles(text).error, 'string', text.slice(0, 30));
    }
    assert.equal(parseHandles(Array.from({ length: 200 }, (_, i) => `u${i}`).join(',')).handles.length, 200);
  });
});

describe('the retry identity (W9.5, D42)', () => {
  it('keys are 128 random bits in hex', () => {
    const keys = new Set(Array.from({ length: 200 }, () => newKey()));
    assert.equal(keys.size, 200);
    for (const key of keys) assert.match(key, /^[0-9a-f]{32}$/);
  });

  it('an unchanged resubmission sends the same key and body; a change mints a new key', () => {
    let n = 0;
    const identity = new RetryIdentity(() => `k${++n}`);
    const first = identity.submission({ to_handle: 'bob', amount: 1500 });
    assert.deepEqual(first, { key: 'k1', body: { to_handle: 'bob', amount: 1500 } });
    assert.deepEqual(identity.submission({ to_handle: 'bob', amount: 1500 }), first, 'a double submit replays');
    identity.touch();
    assert.equal(identity.submission({ to_handle: 'bob', amount: 1500 }).key, 'k2', 'an edited field starts a new payment');
    assert.equal(identity.submission({ to_handle: 'bob', amount: 2000 }).key, 'k3', 'a different body is a new key');
    assert.deepEqual(identity.submission({ to_handle: 'bob', amount: 2000 }), { key: 'k3', body: { to_handle: 'bob', amount: 2000 } });
  });
});

describe('HTML routes and static files (W9.1)', () => {
  let server: Server;
  let port: number;
  before(async () => {
    server = await startServer();
    port = server.port;
    await reset(port, fixture());
  });
  after(() => server.close());

  const HTML = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8';
  const isShell = (reply: { status: number; text: string; headers: Record<string, unknown> }, status = 200) => {
    assert.equal(reply.status, status);
    assert.equal(reply.headers['content-type'], 'text/html; charset=utf-8');
    assert.equal(reply.headers['cache-control'], 'no-store');
    assert.equal(reply.headers['x-content-type-options'], 'nosniff');
    assert.equal(reply.headers['referrer-policy'], 'no-referrer');
    assert.equal(reply.headers['content-security-policy'], CSP);
    assert.match(reply.text, /^<!doctype html>/);
    assert.match(reply.text, /<html lang="en">/);
    assert.match(reply.text, /<link rel="icon" href="data:,">/);
    assert.ok(!/https?:\/\//.test(reply.text), 'nothing from another origin');
  };

  it('serves the shell on /, /split, /signup and /login whatever the Accept header', async () => {
    for (const path of ['/', '/split', '/signup', '/login', '/?x=1', '/login?next=%2F']) {
      for (const accept of [HTML, 'application/json', '*/*', undefined]) {
        isShell(await request(port, 'GET', path, { headers: accept ? { accept } : {} }));
      }
    }
    assert.equal(CSP, "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
      + "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'");
  });

  it('shares /requests and /authorizations with the API: HTML only when Accept lists text/html', async () => {
    const ada = await login(port, 'ada');
    for (const path of ['/requests', '/authorizations', '/requests?direction=incoming', '/authorizations?status=open']) {
      isShell(await request(port, 'GET', path, { headers: { accept: HTML } }));
      isShell(await ada.get(path, { headers: { accept: 'TEXT/HTML ; charset=utf-8' } }));
      for (const accept of ['application/json', '*/*', '', 'text/*', 'text/html;q=0', 'text/html; q=0.000', 'application/xhtml+xml']) {
        const reply = await ada.get(path, { headers: { accept } });
        assert.equal(reply.status, 200, `${path} ${accept}`);
        assert.match(String(reply.headers['content-type']), /^application\/json/);
      }
      const anonymous = await request(port, 'GET', path, { headers: { accept: 'application/json' } });
      assert.equal(anonymous.status, 401);
    }
    const post = await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 1 }, key: 'k', headers: { accept: HTML } });
    assert.equal(post.status, 201, 'POST is always the API');
  });

  it('serves every UI file with its content type and nosniff; any other /assets/ path is 404', async () => {
    const names = readdirSync(new URL('../ui/assets/', import.meta.url));
    assert.ok(names.includes('app.js') && names.includes('app.css'));
    for (const name of names) {
      const reply = await request(port, 'GET', `/assets/${name}`);
      assert.equal(reply.status, 200, name);
      assert.equal(reply.headers['x-content-type-options'], 'nosniff');
      const type = name.endsWith('.js') ? 'text/javascript; charset=utf-8' : name.endsWith('.css') ? 'text/css; charset=utf-8' : 'image/svg+xml';
      assert.equal(reply.headers['content-type'], type, name);
      assert.ok(!/https?:\/\/(?!www\.w3\.org)/.test(reply.text), `${name} loads nothing from another origin`);
    }
    for (const path of ['/assets/', '/assets/nope.js', '/assets/../src/main.ts', '/assets/app.js/x', '/assets']) {
      const reply = await request(port, 'GET', path);
      assert.equal(reply.status, 404, path);
      assert.equal(reply.body?.error?.code, 'not_found');
    }
  });

  it('answers unknown paths with JSON 404, or the HTML 404 screen when Accept lists text/html', async () => {
    for (const path of ['/nowhere', '/me/x', '/assets/nope.js']) {
      const json = await request(port, 'GET', path, { headers: { accept: 'application/json' } });
      assert.equal(json.status, 404);
      assert.equal(json.body.error.code, 'not_found');
      isShell(await request(port, 'GET', path, { headers: { accept: HTML } }), 404);
    }
    const post = await request(port, 'POST', '/login', { headers: { accept: HTML }, json: {} });
    assert.equal(post.status, 404, 'only GET serves pages');
    assert.equal(post.body.error.code, 'not_found');
    const me = await request(port, 'GET', '/me', { headers: { accept: HTML } });
    assert.equal(me.status, 401, 'API paths other than the two shared ones stay JSON');
  });

  it('reads Accept as plan 3.2 says', () => {
    assert.equal(acceptsHtml(undefined), false);
    assert.equal(acceptsHtml(''), false);
    assert.equal(acceptsHtml('*/*'), false);
    assert.equal(acceptsHtml('text/*'), false);
    assert.equal(acceptsHtml('application/json, text/plain'), false);
    assert.equal(acceptsHtml('text/html;q=0'), false);
    assert.equal(acceptsHtml('text/html; q=0.0, */*'), false);
    assert.equal(acceptsHtml('text/html'), true);
    assert.equal(acceptsHtml(' Text/HTML ;level=1'), true);
    assert.equal(acceptsHtml('application/json, text/html;q=0.1'), true);
    assert.equal(acceptsHtml(['application/json', 'text/html']), true);
  });
});
