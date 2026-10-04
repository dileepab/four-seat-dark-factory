// POST /auth/signup and POST /auth/login (spec §6, plan 3.8).

import { readJson, type Ctx, type Result } from '../context.ts';
import { conflict, invalid, malformed, unauthenticated } from '../errors.ts';
import { cpLength, deriveHandle, emailKey, isEmail } from '../fields.ts';
import type { JsonObject } from '../json.ts';
import { hashPassword, issueToken, SIGNUP_COST, verifyPassword } from '../passwords.ts';
import { addUser, newId, nextSeq, store, type User } from '../state.ts';

// Each named field must be a string when present (400) and must be present (422).
function stringFields(body: JsonObject, names: string[]): Record<string, string> {
  for (const name of names) {
    if (Object.hasOwn(body, name) && typeof body[name] !== 'string') throw malformed(`${name} must be a string`);
  }
  for (const name of names) {
    if (!Object.hasOwn(body, name)) throw invalid(`${name} is required`);
  }
  return Object.fromEntries(names.map((name) => [name, body[name] as string]));
}

function session(user: User, token: string): { user_id: string; display_name: string; token: string } {
  return { user_id: user.id, display_name: user.displayName, token };
}

export async function signup(ctx: Ctx): Promise<Result> {
  const { email, password, display_name: displayName } =
    stringFields(readJson(ctx), ['email', 'password', 'display_name']);
  if (!isEmail(email)) throw invalid('email must have the form local@domain');
  const pwLength = cpLength(password);
  if (pwLength < 8 || pwLength > 1024) throw invalid('password must be 8 to 1024 characters');
  const nameLength = cpLength(displayName);
  if (nameLength < 1 || nameLength > 100) throw invalid('display_name must be 1 to 100 characters');

  const key = emailKey(email);
  const handle = deriveHandle(email);
  checkFree(key, handle);
  const hash = await hashPassword(password, SIGNUP_COST);
  // The state may have changed while hashing ran: check again against the live state.
  checkFree(key, handle);
  const st = store.state;
  const user: User = {
    id: newId('u', (id) => st.users.has(id)), email, emailKey: key, password: hash,
    displayName, handle, balance: 0, seq: nextSeq(st),
  };
  addUser(st, user);
  return { status: 201, body: session(user, issueToken(st, user.id)) };
}

function checkFree(key: string, handle: string): void {
  const st = store.state;
  if (st.usersByEmail.has(key)) throw conflict('email_taken', 'that email is already registered');
  if (st.usersByHandle.has(handle)) throw conflict('handle_taken', `the handle ${handle} derived from that email is taken`);
}

export async function login(ctx: Ctx): Promise<Result> {
  const { email, password } = stringFields(readJson(ctx), ['email', 'password']);
  if (!isEmail(email)) throw invalid('email must have the form local@domain');
  // Verification is asynchronous; if a reset or import swapped the state meanwhile,
  // verify again against the live state.
  for (;;) {
    const st = store.state;
    const user = st.usersByEmail.get(emailKey(email));
    if (!user) throw unauthenticated('wrong email or password');
    const ok = await verifyPassword(password, user.password);
    if (store.state !== st) continue;
    if (!ok) throw unauthenticated('wrong email or password');
    return { status: 200, body: session(user, issueToken(st, user.id)) };
  }
}
