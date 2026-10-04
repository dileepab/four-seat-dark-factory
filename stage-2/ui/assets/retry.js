// Retry identity (plan 3.14 "Writes", D42): each idempotent form keeps the key and the exact
// body of its last submission. An unchanged resubmission sends both again, so a double submit
// or a retry after a lost response moves money once; a changed field, or a body that differs
// from the last one sent, mints a new key.

export function newKey(random = (bytes) => crypto.getRandomValues(bytes)) {
  const bytes = random(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function sameJson(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

export class RetryIdentity {
  constructor(mint = newKey) {
    this.mint = mint;
    this.key = null;
    this.body = null;
    this.changed = true;
  }

  // A field of the form changed (an `input` or `change` event).
  touch() {
    this.changed = true;
  }

  // The key and body to send for a submission of `body`.
  submission(body) {
    if (this.changed || this.key === null || !sameJson(body, this.body)) {
      this.key = this.mint();
      this.body = body;
      this.changed = false;
    }
    return { key: this.key, body: this.body };
  }
}
