// The route table. An unknown path, or a known path with another method, is 404 (D3).

import type { Ctx, Result } from './context.ts';
import { login, signup } from './handlers/auth.ts';
import {
  captureAuthorization, createAuthorization, listAuthorizations, voidAuthorization,
} from './handlers/authorizations.ts';
import { me } from './handlers/me.ts';
import { statement } from './handlers/statement.ts';
import { activity, createPayment } from './handlers/payments.ts';
import { cancelRequest, createRequest, declineRequest, listRequests, payRequest } from './handlers/requests.ts';
import { createSettlement } from './handlers/settlements.ts';
import { createSplit } from './handlers/splits.ts';
import { exportSnapshot, health, importSnapshot, reset } from './handlers/system.ts';

export interface Route {
  method: string;
  path: string; // literal path, or a pattern with one `{id}` segment
  testBody?: boolean; // reset and import take the larger body limit
  handler: (ctx: Ctx) => Result | Promise<Result>;
}

const ROUTES: Route[] = [
  { method: 'GET', path: '/health', handler: health },
  { method: 'POST', path: '/_test/reset', testBody: true, handler: reset },
  { method: 'GET', path: '/_test/export', handler: exportSnapshot },
  { method: 'POST', path: '/_test/import', testBody: true, handler: importSnapshot },
  { method: 'POST', path: '/auth/signup', handler: signup },
  { method: 'POST', path: '/auth/login', handler: login },
  { method: 'GET', path: '/me', handler: me },
  { method: 'GET', path: '/statement', handler: statement },
  { method: 'POST', path: '/payments', handler: createPayment },
  { method: 'GET', path: '/activity', handler: activity },
  { method: 'POST', path: '/requests', handler: createRequest },
  { method: 'GET', path: '/requests', handler: listRequests },
  { method: 'POST', path: '/requests/{id}/pay', handler: payRequest },
  { method: 'POST', path: '/requests/{id}/decline', handler: declineRequest },
  { method: 'POST', path: '/requests/{id}/cancel', handler: cancelRequest },
  { method: 'POST', path: '/splits', handler: createSplit },
  { method: 'POST', path: '/settlements', handler: createSettlement },
  { method: 'POST', path: '/authorizations', handler: createAuthorization },
  { method: 'GET', path: '/authorizations', handler: listAuthorizations },
  { method: 'POST', path: '/authorizations/{id}/capture', handler: captureAuthorization },
  { method: 'POST', path: '/authorizations/{id}/void', handler: voidAuthorization },
];

export interface RouteMatch {
  route: Route;
  path: string;
  params: Record<string, string>;
}

export function matchRoute(method: string, rawPath: string): RouteMatch | null {
  const segments = rawPath.split('/');
  for (const route of ROUTES) {
    if (route.method !== method) continue;
    if (!route.path.includes('{')) {
      if (route.path === rawPath) return { route, path: rawPath, params: {} };
      continue;
    }
    const pattern = route.path.split('/');
    if (pattern.length !== segments.length) continue;
    const params: Record<string, string> = {};
    let ok = true;
    for (let i = 0; i < pattern.length && ok; i++) {
      const part = pattern[i];
      if (part.startsWith('{')) {
        const value = decodeSegment(segments[i]);
        if (value === null || value === '') ok = false;
        else params[part.slice(1, -1)] = value;
      } else if (part !== segments[i]) {
        ok = false;
      }
    }
    if (ok) {
      const path = pattern.map((part) => (part.startsWith('{') ? params[part.slice(1, -1)] : part)).join('/');
      return { route, path, params };
    }
  }
  return null;
}

function decodeSegment(segment: string): string | null {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}
