// Unauthenticated service endpoints: health and the reset, export and import test hooks.

import { readJson, type Ctx, type Result } from '../context.ts';
import { buildState, validateFixture } from '../fixture.ts';
import { exportState, importState } from '../snapshot.ts';
import { store, swapState } from '../state.ts';

export function health(): Result {
  return { status: 200, body: { status: 'ok' } };
}

// Validate everything first, build the new state aside, then swap it in one step:
// a rejected fixture changes nothing (I25).
export async function reset(ctx: Ctx): Promise<Result> {
  const fixture = validateFixture(readJson(ctx));
  swapState(await buildState(fixture));
  return { status: 204 };
}

export function exportSnapshot(): Result {
  return { status: 200, body: exportState(store.state) };
}

// Full validation first (422, nothing changes), then one synchronous swap.
export function importSnapshot(ctx: Ctx): Result {
  swapState(importState(readJson(ctx)));
  return { status: 204 };
}
