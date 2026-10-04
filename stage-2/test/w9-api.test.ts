// W9/W10: the page's calls to the API (ui/assets/api.js), with `fetch` replaced. The three
// outcomes of plan 3.14 and D43, the 4 s limit from both sides, and the list reader (D64).

import assert from 'node:assert/strict';
import { afterEach, describe, it } from 'node:test';
// @ts-expect-error plain browser JavaScript modules
import { call, readAll, TIMEOUT_MS } from '../ui/assets/api.js';

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

type Answer = { status: number; body: string } | 'network' | 'never' | { after: number; status: number; body: string };

// Replace fetch: each call takes the next answer; the paths asked for are recorded.
function serve(...answers: Answer[]): string[] {
  const asked: string[] = [];
  globalThis.fetch = (async (path: string, init: RequestInit) => {
    asked.push(path);
    const answer = answers.shift();
    if (answer === undefined) throw new Error(`no answer left for ${path}`);
    if (answer === 'network') throw new TypeError('Failed to fetch');
    const signal = init.signal!;
    const aborted = new Promise<never>((_, reject) => signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))));
    if (answer === 'never') return aborted;
    const respond = () => new Response(answer.body === '' ? null : answer.body, { status: answer.status });
    if ('after' in answer) {
      return Promise.race([aborted, new Promise<Response>((resolve) => setTimeout(() => resolve(respond()), answer.after))]);
    }
    return respond();
  }) as typeof fetch;
  return asked;
}

const json = (status: number, value: unknown) => ({ status, body: JSON.stringify(value) });
const envelope = (code: string, message = 'nope') => ({ error: { code, message } });

describe('call(): ok, refused or unknown (3.14 Outcomes, D43)', () => {
  it('a 2xx is ok only when its body is a JSON object', async () => {
    serve(json(201, { payment_id: 'p_1', amount: 100 }), json(200, { payment_id: 'p_1' }));
    assert.deepEqual(await call('POST', '/payments', { body: {}, key: 'k' }), { kind: 'ok', status: 201, data: { payment_id: 'p_1', amount: 100 } });
    assert.equal((await call('POST', '/payments', { body: {}, key: 'k' })).kind, 'ok', 'a 200 replay');

    // Committed, then an answer the page cannot read as the result: unknown, never ok (critic P1).
    for (const body of ['', 'null', '[]', '"ok"', '5', 'true', 'not json', '{"amount": 1']) {
      serve({ status: 201, body });
      const outcome = await call('POST', '/payments', { body: {}, key: 'k' });
      assert.equal(outcome.kind, 'unknown', `201 with body ${JSON.stringify(body)}`);
    }
    serve({ status: 204, body: '' });
    assert.equal((await call('POST', '/payments', { body: {}, key: 'k' })).kind, 'unknown', '204 carries no result');
  });

  it('only a 4xx with the error envelope is a refusal, with a message for people', async () => {
    serve(json(409, envelope('insufficient_funds')), json(422, envelope('validation_failed', 'amount must be positive')));
    assert.deepEqual(await call('POST', '/payments', { body: {}, key: 'k' }),
      { kind: 'refused', status: 409, code: 'insufficient_funds', message: 'Not enough available funds. Money on hold cannot be spent.' });
    const second = await call('POST', '/payments', { body: {}, key: 'k' });
    assert.deepEqual([second.kind, second.message], ['refused', 'Amount must be positive.']);

    const unknowns: [string, Answer][] = [
      ['429 JSON without the envelope (critic U04)', json(429, { retry_after: 1 })],
      ['400 with an empty body', { status: 400, body: '' }],
      ['404 with HTML', { status: 404, body: '<h1>no</h1>' }],
      ['422 with a code that is not a string', json(422, { error: { code: 5, message: 'x' } })],
      ['500 with the envelope', json(500, envelope('internal'))],
      ['503 with nothing', { status: 503, body: '' }],
      ['302', { status: 302, body: '' }],
      ['a network failure', 'network'],
    ];
    for (const [label, answer] of unknowns) {
      serve(answer);
      assert.equal((await call('POST', '/payments', { body: {}, key: 'k' })).kind, 'unknown', label);
    }
  });

  it('waits up to 4 s: an answer at 2.8 s is ok; no answer is unknown before 4.7 s (critic U01, U02)', async () => {
    assert.equal(TIMEOUT_MS, 4000);
    serve({ after: 2800, ...json(201, { payment_id: 'p_1' }) });
    let started = Date.now();
    assert.equal((await call('POST', '/payments', { body: {}, key: 'k' })).kind, 'ok');
    assert.ok(Date.now() - started >= 2700);

    serve('never');
    started = Date.now();
    const outcome = await call('POST', '/payments', { body: {}, key: 'k' });
    const waited = Date.now() - started;
    assert.deepEqual(outcome, { kind: 'unknown', reason: 'timeout' });
    assert.ok(waited >= 3900 && waited < 4700, `gave up after ${waited} ms`);
  });
});

describe('readAll(): every page from the bare path (D64)', () => {
  const page = (ids: string[], more: boolean) => json(200, { payments: ids.map((id) => ({ payment_id: id })), has_more: more });
  const ids = (n: number, from = 0) => Array.from({ length: n }, (_, i) => `p_${String(from + i).padStart(3, '0')}`);

  it('reads the bare path, then offset pages, keeping each item once (critic U06)', async () => {
    // A payment created between the reads pushes p_049 from page 1 onto page 2.
    const asked = serve(page(ids(50), true), page([...ids(1, 49), ...ids(10, 50)], false));
    const outcome = await readAll('/activity', 'payments', (p: { payment_id: string }) => p.payment_id);
    assert.deepEqual(asked, ['/activity', '/activity?offset=50&limit=200']);
    assert.equal(outcome.kind, 'ok');
    assert.deepEqual(outcome.data.map((p: { payment_id: string }) => p.payment_id), ids(60));
  });

  it('a failed or unreadable later page fails the whole read, never a partial list (critic U30)', async () => {
    for (const [label, second] of [
      ['a 500', json(500, envelope('internal'))],
      ['a network failure', 'network'],
      ['a page without its list', json(200, { has_more: false })],
      ['a list that is not an array', json(200, { payments: { p_1: {} }, has_more: false })],
    ] as [string, Answer][]) {
      serve(page(ids(50), true), second);
      const outcome = await readAll('/activity', 'payments', (p: { payment_id: string }) => p.payment_id);
      assert.notEqual(outcome.kind, 'ok', label);
    }
    serve(json(200, { has_more: false }));
    assert.equal((await readAll('/activity', 'payments', (p: { payment_id: string }) => p.payment_id)).kind, 'unknown',
      'a first page without its list');
  });
});
