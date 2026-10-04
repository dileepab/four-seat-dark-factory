// The HTTP server: transport, body reading, routing and the error envelope.

import http from 'node:http';
import type { Duplex } from 'node:stream';
import type { Ctx, Result } from './context.ts';
import { ApiError, errorBody, notFound } from './errors.ts';
import { MAX_DEPTH } from './json.ts';
import { matchRoute } from './routes.ts';
import { notFoundPage, uiResponse } from './ui.ts';

const API_BODY_LIMIT = 1024 * 1024; // 1 MiB (D8)
const TEST_BODY_LIMIT = 64 * 1024 * 1024; // reset and import (D8)
// An export wraps stored request bodies (themselves up to MAX_DEPTH deep) in a few levels.
const TEST_BODY_DEPTH = MAX_DEPTH + 16;
const MAX_HEADER_SIZE = 1024 * 1024 + 16 * 1024; // header blocks up to 1 MiB (D28)
// Idle keep-alive connections outlive any client pool's idle reuse window (D35).
const KEEP_ALIVE_TIMEOUT = 65_000;
const HEADERS_TIMEOUT = 66_000;

class BodyAborted extends Error {}

export function createApp(): http.Server {
  const server = http.createServer({ maxHeaderSize: MAX_HEADER_SIZE }, (req, res) => {
    void serve(req, res);
  });
  server.keepAliveTimeout = KEEP_ALIVE_TIMEOUT;
  server.headersTimeout = HEADERS_TIMEOUT;
  server.on('clientError', answerClientError);
  return server;
}

async function serve(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  try {
    const result = await dispatch(req);
    if (result.raw) sendRaw(res, result.status, result.raw);
    else send(res, result.status, result.body);
  } catch (err) {
    if (err instanceof ApiError) {
      send(res, err.status, errorBody(err.code, err.message));
    } else if (err instanceof BodyAborted) {
      res.destroy();
    } else {
      console.error(err);
      send(res, 500, errorBody('internal_error', 'unexpected server error'));
    }
  }
}

async function dispatch(req: http.IncomingMessage): Promise<Result> {
  const method = req.method ?? 'GET';
  const target = req.url ?? '/';
  const q = target.indexOf('?');
  const rawPath = q < 0 ? target : target.slice(0, q);
  const query = new URLSearchParams(q < 0 ? '' : target.slice(q + 1));
  // The UI's pages and files answer GETs before the API's routes (plan 3.14, D40).
  const page = method === 'GET' ? uiResponse(rawPath, req.headers.accept) : null;
  const match = page ? null : matchRoute(method, rawPath);
  // The body is always drained, so the client can read the answer whatever it is.
  const { body, tooLarge } = await readBody(req, match?.route.testBody ? TEST_BODY_LIMIT : API_BODY_LIMIT);
  if (page) return page;
  if (!match) {
    const missing = method === 'GET' ? notFoundPage(req.headers.accept) : null;
    if (missing) return missing;
    // The path is not echoed: a probe such as /assets/%2e%2e/Dockerfile gets nothing back of it.
    throw notFound(`no route for ${method} on this path`);
  }
  const ctx: Ctx = {
    method, path: match.path, query, headers: req.headers, params: match.params, body, tooLarge,
    maxDepth: match.route.testBody ? TEST_BODY_DEPTH : MAX_DEPTH,
  };
  return await match.route.handler(ctx);
}

function readBody(req: http.IncomingMessage, limit: number): Promise<{ body: Buffer; tooLarge: boolean }> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    let tooLarge = false;
    let settled = false;
    req.on('data', (chunk: Buffer) => {
      size += chunk.length;
      if (tooLarge) return;
      if (size > limit) {
        tooLarge = true;
        chunks.length = 0;
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      settled = true;
      resolve({ body: tooLarge ? Buffer.alloc(0) : Buffer.concat(chunks), tooLarge });
    });
    const abort = () => {
      if (!settled) {
        settled = true;
        reject(new BodyAborted());
      }
    };
    req.on('error', abort);
    req.on('close', abort);
  });
}

function send(res: http.ServerResponse, status: number, body: unknown): void {
  if (res.headersSent || res.destroyed) return;
  if (status === 204 || body === undefined) {
    res.writeHead(status);
    res.end();
    return;
  }
  const text = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(text),
  });
  res.end(text);
}

function sendRaw(res: http.ServerResponse, status: number, raw: { headers: Record<string, string>; body: Buffer }): void {
  if (res.headersSent || res.destroyed) return;
  res.writeHead(status, { ...raw.headers, 'Content-Length': raw.body.length });
  res.end(raw.body);
}

// Requests the HTTP parser itself refuses still get the envelope (D28).
function answerClientError(err: Error & { code?: string }, socket: Duplex): void {
  if (err.code === 'ECONNRESET' || !socket.writable) {
    socket.destroy();
    return;
  }
  const oversized = err.code === 'HPE_HEADER_OVERFLOW';
  const status = oversized ? 422 : 400;
  const text = JSON.stringify(oversized
    ? errorBody('validation_failed', 'the request headers are too large')
    : errorBody('malformed_request', 'the request could not be parsed'));
  socket.end(
    `HTTP/1.1 ${status} ${oversized ? 'Unprocessable Entity' : 'Bad Request'}\r\n`
    + 'Content-Type: application/json; charset=utf-8\r\n'
    + `Content-Length: ${Buffer.byteLength(text)}\r\n`
    + 'Connection: close\r\n\r\n'
    + text,
  );
}
