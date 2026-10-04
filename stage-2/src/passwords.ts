// Password hashing (scrypt, per-account salt, D22) and bearer tokens (D30).

import { createHash, randomBytes, scrypt, timingSafeEqual } from 'node:crypto';
import type { PasswordHash, State } from './state.ts';

export interface ScryptParams {
  N: number;
  r: number;
  p: number;
}

// Signup cost. Seeded accounts use a lower cost so a 1000-user reset fits in 10 s.
export const SIGNUP_COST: ScryptParams = { N: 2 ** 14, r: 8, p: 1 };
export const SEED_COST: ScryptParams = { N: 2 ** 12, r: 8, p: 1 };

const KEY_LENGTH = 32;
const SALT_LENGTH = 16;
const MAX_MEM = 256 * 1024 * 1024;

function derive(password: string, salt: Buffer, params: ScryptParams): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    scrypt(password, salt, KEY_LENGTH, { N: params.N, r: params.r, p: params.p, maxmem: MAX_MEM },
      (err, key) => (err ? reject(err) : resolve(key)));
  });
}

export async function hashPassword(password: string, params: ScryptParams): Promise<PasswordHash> {
  const salt = randomBytes(SALT_LENGTH);
  const key = await derive(password, salt, params);
  return {
    alg: 'scrypt', N: params.N, r: params.r, p: params.p,
    salt: salt.toString('base64'), hash: key.toString('base64'),
  };
}

export async function verifyPassword(password: string, record: PasswordHash): Promise<boolean> {
  const expected = Buffer.from(record.hash, 'base64');
  const key = await derive(password, Buffer.from(record.salt, 'base64'), record);
  return key.length === expected.length && timingSafeEqual(key, expected);
}

export function tokenDigest(token: string): string {
  return createHash('sha256').update(token).digest('hex');
}

// 256 random bits; only the digest is kept in state.
export function issueToken(st: State, userId: string): string {
  const token = randomBytes(32).toString('base64url');
  st.tokens.set(tokenDigest(token), userId);
  return token;
}
