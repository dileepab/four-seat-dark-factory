// GET /me (spec §8; stage 2 adds the money fields, plan 3.6; stage 3 the historical views).

import { authenticate, instantParam, type Ctx, type Result } from '../context.ts';
import { heldIn, totalIn } from '../history.ts';
import { msKey } from '../instant.ts';
import { clock, heldBy, store } from '../state.ts';

export function me(ctx: Ctx): Result {
  const user = authenticate(ctx);
  const asOf = instantParam(ctx, 'as_of');
  const knownAt = instantParam(ctx, 'known_at');
  const st = store.state;
  const now = clock(st);
  const who = { user_id: user.id, display_name: user.displayName, handle: user.handle };
  const units = { currency: st.currency, minor_units: st.minorUnits };
  if (asOf === null && knownAt === null) {
    const held = heldBy(st, user.id, now.ms);
    return {
      status: 200,
      body: { ...who, balance: user.balance, total: user.balance, available: user.balance - held, held, ...units },
    };
  }
  // The view (plan 3.7, 3.8): effective at `as_of` (else the read's instant), as known at
  // `known_at` (else everything recorded before the read began).
  const view = { T: asOf?.key ?? msKey(now.ms), K: knownAt?.key ?? null, C: st.seq };
  const total = totalIn(st, user, view);
  const held = heldIn(st, user, view);
  const body: Record<string, unknown> = { ...who, balance: total, total, available: total - held, held, ...units };
  if (asOf !== null) body.as_of = asOf.text;
  if (knownAt !== null) body.known_at = knownAt.text;
  return { status: 200, body };
}
