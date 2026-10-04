// POST /splits (spec §8, §9): equal shares, one pending request per other participant.

import { authenticate, readJson, type Ctx, type Result } from '../context.ts';
import { invalid, malformed, notFound } from '../errors.ts';
import { optionalNote, requireAmount } from '../fields.ts';
import { idempotencyKey, idempotent } from '../idempotency.ts';
import { has, type JsonObject } from '../json.ts';
import { newId, nextSeq, nextTs, type Share, type Split, type User } from '../state.ts';
import { splitView } from '../views.ts';
import { openRequest } from './requests.ts';

const MAX_PARTICIPANTS = 200; // D20

// Spec §9: whole units that sum to `amount` and differ by at most one, the larger shares
// going to the earliest participants.
export function equalShares(amount: number, n: number): number[] {
  const base = Math.floor(amount / n);
  const remainder = amount - base * n;
  return Array.from({ length: n }, (_, i) => base + (i < remainder ? 1 : 0));
}

function participantHandles(body: JsonObject): string[] {
  const handles = body.participant_handles;
  if (handles.length === 0) throw invalid('participant_handles must not be empty');
  if (handles.length > MAX_PARTICIPANTS) throw invalid(`participant_handles takes at most ${MAX_PARTICIPANTS} handles`);
  if (new Set(handles).size !== handles.length) throw invalid('participant_handles must not repeat a handle');
  return handles;
}

export function createSplit(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const key = idempotencyKey(ctx);
  const body = readJson(ctx);
  return idempotent(ctx, caller, key, body, (st) => {
    const handles = body.participant_handles;
    if (has(body, 'participant_handles')
      && (!Array.isArray(handles) || handles.some((h) => typeof h !== 'string'))) {
      throw malformed('participant_handles must be an array of strings');
    }
    const amount = requireAmount(body);
    if (!has(body, 'participant_handles')) throw invalid('participant_handles is required');
    const list = participantHandles(body);
    const note = optionalNote(body);
    const participants: User[] = list.map((handle) => {
      const user = st.usersByHandle.get(handle);
      if (!user) throw notFound(`no user has the handle ${handle}`);
      return user;
    });

    const amounts = equalShares(amount, participants.length);
    const createdAt = nextTs(st);
    const shares: Share[] = participants.map((u, i) => ({ handle: u.handle, amount: amounts[i] }));
    const requestIds = participants
      .map((u, i) => (u.id === caller.id ? null : openRequest(st, caller, u, amounts[i], note, createdAt).id))
      .filter((id): id is string => id !== null);
    const split: Split = {
      id: newId('sp', (id) => st.splits.has(id)),
      creatorId: caller.id, amount, note, shares, requestIds, createdAt, seq: nextSeq(st),
    };
    st.splits.set(split.id, split);
    return splitView(st, split);
  });
}
