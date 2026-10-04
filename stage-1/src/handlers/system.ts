// Unauthenticated service endpoints: health and the reset test hook.

import { readJson, type Ctx, type Result } from '../context.ts';
import { buildState, validateFixture } from '../fixture.ts';
import { swapState } from '../state.ts';

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
