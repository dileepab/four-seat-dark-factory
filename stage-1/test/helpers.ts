// Builder test helpers: an in-process server on a free port and a small JSON client.

import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { createApp } from '../src/app.ts';

export interface Server {
  base: string;
  port: number;
  close: () => Promise<void>;
}

export async function startServer(): Promise<Server> {
  const server = createApp();
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as AddressInfo;
  return {
    base: `http://127.0.0.1:${port}`,
    port,
    close: () => new Promise<void>((resolve) => {
      server.closeAllConnections();
      server.close(() => resolve());
    }),
  };
}

export interface Reply {
  status: number;
  body: any;
  text: string;
  headers: http.IncomingHttpHeaders;
}

export interface CallOptions {
  json?: unknown;
  raw?: string | Buffer;
  key?: string;
  token?: string | null;
  headers?: Record<string, string>;
}

// A raw node:http call, so tests control every byte and header that is sent.
export function request(port: number, method: string, path: string, opts: CallOptions = {}): Promise<Reply> {
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (opts.token) headers.authorization = `Bearer ${opts.token}`;
  if (opts.key !== undefined) headers['idempotency-key'] = opts.key;
  let payload: Buffer | undefined;
  if (opts.raw !== undefined) payload = Buffer.isBuffer(opts.raw) ? opts.raw : Buffer.from(opts.raw);
  else if (opts.json !== undefined) payload = Buffer.from(JSON.stringify(opts.json));
  if (payload) {
    headers['content-type'] ??= 'application/json';
    headers['content-length'] = String(payload.length);
  }
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, method, path, headers }, (res) => {
      const chunks: Buffer[] = [];
      res.on('data', (c: Buffer) => chunks.push(c));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        let body: any = null;
        try {
          body = text ? JSON.parse(text) : null;
        } catch {
          body = undefined;
        }
        resolve({ status: res.statusCode ?? 0, body, text, headers: res.headers });
      });
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

export class Client {
  port: number;
  token: string | null;

  constructor(port: number, token: string | null = null) {
    this.port = port;
    this.token = token;
  }

  call(method: string, path: string, opts: CallOptions = {}): Promise<Reply> {
    return request(this.port, method, path, { token: this.token, ...opts });
  }

  get(path: string, opts: CallOptions = {}): Promise<Reply> {
    return this.call('GET', path, opts);
  }

  post(path: string, opts: CallOptions = {}): Promise<Reply> {
    return this.call('POST', path, opts);
  }
}

export const PASSWORD = 'correct horse';

export function user(handle: string, balance: number, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: `u_${handle}`, email: `${handle}@example.com`, password: PASSWORD,
    display_name: handle[0].toUpperCase() + handle.slice(1), handle, balance, ...extra,
  };
}

export function fixture(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    currency: 'EUR', minor_units: 2,
    users: [user('ada', 10_000), user('bob', 2_500), user('cy', 500)],
    payments: [], requests: [],
    ...extra,
  };
}

export async function reset(port: number, body: unknown = fixture()): Promise<void> {
  const reply = await request(port, 'POST', '/_test/reset', { json: body });
  if (reply.status !== 204) throw new Error(`reset failed: ${reply.status} ${reply.text}`);
}

export async function login(port: number, handle: string, password = PASSWORD): Promise<Client> {
  const reply = await request(port, 'POST', '/auth/login', { json: { email: `${handle}@example.com`, password } });
  if (reply.status !== 200) throw new Error(`login failed: ${reply.status} ${reply.text}`);
  return new Client(port, reply.body.token);
}

export function isEnvelope(reply: Reply, status: number, code: string): boolean {
  return reply.status === status
    && typeof reply.body?.error?.message === 'string'
    && reply.body?.error?.code === code;
}

export function expectError(reply: Reply, status: number, code: string): void {
  if (!isEnvelope(reply, status, code)) {
    throw new Error(`expected ${status} ${code}, got ${reply.status} ${reply.text.slice(0, 300)}`);
  }
}
