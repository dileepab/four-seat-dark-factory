// GET /me (spec §8; stage 2 adds the money fields, plan 3.6).

import { authenticate, type Ctx, type Result } from '../context.ts';
import { clock, heldBy, store } from '../state.ts';

export function me(ctx: Ctx): Result {
  const user = authenticate(ctx);
  const st = store.state;
  const held = heldBy(st, user.id, clock(st).ms);
  return {
    status: 200,
    body: {
      user_id: user.id, display_name: user.displayName, handle: user.handle,
      balance: user.balance, total: user.balance, available: user.balance - held, held,
      currency: st.currency, minor_units: st.minorUnits,
    },
  };
}
