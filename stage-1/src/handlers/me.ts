// GET /me (spec §8).

import { authenticate, type Ctx, type Result } from '../context.ts';
import { store } from '../state.ts';

export function me(ctx: Ctx): Result {
  const user = authenticate(ctx);
  const st = store.state;
  return {
    status: 200,
    body: {
      user_id: user.id, display_name: user.displayName, handle: user.handle,
      balance: user.balance, currency: st.currency, minor_units: st.minorUnits,
    },
  };
}
