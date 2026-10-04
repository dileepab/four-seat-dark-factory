# Stage 3 review (critic-h6bj)

Each entry records one verdict: the commit, the verdict, the reason and the evidence I checked. My scratch work lives under `.work/critic-h6bj/`.

## Plan review: stage-3/PLAN.md @ 4497d6f (not a verdict)

I read the following against `stage-3/PLAN.md` at 4497d6f:
- `stage-3.md` in full;
- `stage-2.md` in full;
- the parts of `stage-1.md` that stage 3 changes or relies on: §3.4, §4, §5, §7, §8 (paging and the feed), §10 and §11;
- the supplied checks `test/stage_3/test_sample.py`, with the track's `conftest.py` and `fixtures.py`;
- `stage-4.md`, only for the export look-ahead in section 1.

I also read the stage-2 code that the plan says carries over unchanged, one level below its clauses:
- `stage-2/src/snapshot.ts`: import validation and the clock base;
- `stage-2/src/time.ts`: `rfc3339Ms`;
- `stage-2/src/state.ts`: held funds;
- `stage-2/src/fixture.ts`: seeded authorizations.

The builder's W14 handoff (e98c86a) arrived while I was writing. Where it already does what a point below asks, I say so. Its code is reviewed in its own entry.

Sent to the planner as one batch: 3 defects, 2 smaller defects, 2 wording fixes, 5 criteria to add, and polish recorded.

### Defects

1. **Section 3.8 never says which captures count, so the historical `held` can disagree with the current one** (3.8, I60, W14.6, W17.3).
   - 3.8 says: "A capture counts when its payment's `created_at` is at or before T ... Otherwise A holds its `amount` minus the captures that count."
   - A seeded `open` authorization may carry `captured_amount` > 0 with no capture payment (stage-2 3.11). Stage 2 holds `amount − captured_amount` for it (`stage-2/src/state.ts:256`, `:277`).
   - Under 3.8 as written, nothing counts for that seeded amount, so the hold holds its full `amount` at every T from its creation. Then:
     - `GET /me?as_of=<now>` disagrees with `GET /me` in `held` and `available`. So does `GET /me?known_at=<future>`, whose T is the read's instant.
     - Step 13's overdraft check sees too little `available` and refuses valid corrections. Example:
       - Ada has balance 1000 and a seeded hold of 1000 with 300 captured, so she has 300 available.
       - She pays Bob 100.
       - She corrects that payment to 300. The debit is 200 and she has 200 available, so the correction is valid.
       - The check reads `available` after the payment as 700 − 1000 = −300 and answers `historical_overdraft`.
   - The opposite also goes wrong. A seeded `payment_ids` entry, or a seeded payment's `authorization_id`, is a display-only link (D62) that may name any payment. Counting those links counts money twice, or counts money from a hold between other people.
   - Asked for:
     - Define the captures that count for A in a view: A's seeded `captured_amount`, counted from A's creation, plus the payments made by `POST /authorizations/{A}/capture` with `created_at` at or before T and K. Display-only links are never followed.
     - Say how schema 3 carries the seeded part, and how a schema-2 import tells API captures from seeded ones.
     - A new invariant: for any T at or after the latest event and before the next deadline, `GET /me?as_of=T` equals `GET /me` in all four money fields. So do `GET /me?known_at=<future>` and `GET /me?as_of=<the read's instant>`. Test it with:
       - a seeded, partly captured open hold;
       - an API hold after a nonfinal capture;
       - a hold imported from a stage-2 export.
   - W14 (handoff item 6) already counts a seeded `captured_amount` from creation. I review its handling of claimed links in the W14 entry.
2. **A seeded closed hold that has a supplied `created_at` needs a marker the export does not carry** (3.8 first bullet, 3.10, D68, I61, 3.11, I26).
   - D68 lets any seeded authorization carry `created_at`; take a `voided` one created 3 hours before the reset.
   - I61 gives it `closed_at` = the reset's timestamp, and 3.8's first bullet says it "holds nothing at any instant".
   - After an export and import, nothing in the 3.11 state separates it from a hold that was created then and voided at the reset. The general rules would make it hold its amount from `created_at` until the reset, so `GET /me?as_of=<in between>` changes across a round trip.
   - Asked for, either:
     - (simplest) a seeded closed authorization's `closed_at` is its `created_at`: the supplied one, else the reset's timestamp, which is what stage 2 recorded. Bullets 2 and 4 of 3.8 then give "nothing at any instant" with no marker. 3.11 must then accept any 3.4 instant for `closed_at`, not only the service form;
     - or the marker in the schema-3 state, with a W17.2 round-trip criterion.
3. **3.11 keeps the schema-2 rule for every `created_at`, which refuses this service's own exports** (3.11, §10, I26, I65, W17.2).
   - "Schemas 1 and 2 import by their earlier rules ... Schema-3 validation adds ..." leaves schema 2's rule in force. That rule allows only the service form `YYYY-MM-DDTHH:MM:SS.sss+00:00` (`stage-2/src/snapshot.ts:23`, used at `:180` and `:262`).
   - Stage 3 stores seeded payment and authorization `created_at` exactly as written. A reset seeding `created_at: "2026-09-20T12:00:00+00:00"` (the specification's own form) followed by an export and an import would answer 422, against §10's "It must accept an unchanged export produced by this service".
   - Stage 2 also takes the clock base as the string maximum of every record's time (`snapshot.ts:146`, `:265`). String order is not instant order for mixed offsets, precisions or case:
     - `2026-10-04T23:30:00+23:00`, which is 00:30Z, sorts after `2026-10-04T14:00:00.000+00:00`;
     - a lowercase `t` sorts after every `T`.
   - Asked for:
     - 3.11: payment and authorization `created_at`, and `closed_at` under point 2, accept the 3.4 grammar. Every comparison during import is by exact instant. `recorded_at` strictly increases as instants, since revision 1's value is the seeded string.
     - A W17.2 criterion: a round trip of a state seeded in each accepted form (no fraction, `Z`, `z`, `t`, `+05:30`, `-00:00`, microseconds) gives 204, the same reads (feed order, statements, `as_of`, revisions), and new writes later than everything imported.
   - W14's `snapshot.ts` already accepts instants for both `created_at` fields and compares `last_ts` by instant. So this asks the plan to catch up, plus the test.

### Smaller defects

4. **D72 refuses a future `from` when `to` is omitted, although nothing contradicts there** (D72, 3.9, W15.2).
   - Every selected effective time is at or before the read's instant R:
     - corrections need `effective_at` ≤ now;
     - seeded times are at or before the reset;
     - issued times are at or before R.
   - So with `to` defaulted to R + 1 ms, no entry can fall in `[to, from)`. Requirement 2 and requirement 3 then agree: no entries, and opening = closing = the balance at R.
   - The specification says "Both query instants may be in the future". `GET /statement?from=<in an hour>` is a natural check for that, and D72 answers it 422.
   - Asked for: keep 422 only when both bounds are given and `from` is later than `to`. With `to` omitted, a later `from` is the empty window (opening = closing = the balance at R) and gets a snapshot.
5. **I50 weakens "before" to "not later than"** (I50, W14.1).
   - The specification says an omitted seeded `created_at` "uses reset time, before subsequent API-created payments".
   - 3.5 already makes the first API write at least 1 ms after the reset. But a test written to I50 accepts a tie, and a tie lets the statement put a later API payment ahead of a seeded one by id.
   - Asked for: "earlier than" in I50, and W14.1 asserting strictly earlier for the first payment and the first authorization after a reset.

### Wording

6. Two wordings in 3.9 and D72:
   - 3.9 says a first read returns "its first page". The result bullet says the page is `[offset, offset + limit)`. Say "the requested page": a first read honours `offset`.
   - D72 says a snapshot read has "the same top-level fields". Say what it means: `snapshot` is the token it was given, and the read stores nothing.

### Criteria to add (one level below the boundaries the plan names)

7. These are the boundaries one level below the ones the criteria name:
   - **B1 (W14.6):** sub-millisecond hold boundaries. Seed an open hold whose `created_at` and `expires_at` carry microseconds (for example `...30.123456+05:30`). Check:
     - `as_of` 1 µs before `created_at` holds 0, and exactly at it holds the amount;
     - `as_of` 1 µs before `expires_at` holds the amount, and exactly at it holds 0.
     - Why: stage 2's `rfc3339Ms` rounds up to whole milliseconds (`stage-2/src/time.ts:13-36`), which is exact only against a millisecond clock. Reusing it for `as_of` keeps the funds held for up to 1 ms past the deadline.
   - **B2 (W14.6, W14.7):** inclusive event times, using the service's own strings. `as_of` exactly at each of these gives the new state, and 1 µs earlier gives the previous one:
     - an API hold's `created_at`;
     - a nonfinal capture's `created_at`;
     - a void's or a final capture's `closed_at`.
     - Also check that a closing capture's `closed_at` equals its payment's `created_at`.
   - **B3 (W16.9):** `known_at` exactly at a correction's `recorded_at` selects the new revision, and 1 µs before selects the previous one ("recorded at or before").
   - **B4 (W16.9, T44):** a payment corrected to 0 still appears in a statement that covers its `effective_at`. It is one entry with `delta` 0, `payment.amount` 0 and the new revision number.
   - **B5 (W14.1, W15.1):** the order tests seed instants whose string order disagrees with their instant order:
     - `+05:30` against `Z`;
     - `...:00Z` against `...:00.000001Z`;
     - a lowercase `t`.
     - Do this for the feed, for `GET /authorizations` and for the statement.

### Checked and fine

- The instant grammar and exact comparison (3.4, D66).
- The leap-second refusal.
- D67. The default `to` = R + 1 ms is needed, since an issued time can equal R. It is also enough, since nothing selected lies after R.
- D69. Stage-1 and stage-2 fixtures do not add up, and the specification states no reset error.
- D70 and D73 within stage 3:
  - payment representations never change after creation, and revisions are only appended, so recomputing by cutoff reproduces a snapshot exactly;
  - the creation sequence and each payment's `seq` survive export (`stage-2/src/snapshot.ts:48`).
- D74 against the specification's own order.
- D79, D80, D81 and D82. D81's strictness also keeps every effective time at or before any later read's instant.
- D83, and the 404 of the revisions endpoint.
- I1 in every (T, K) view, by construction.
- I2's nonnegative history:
  - new payments are always the latest in effective time;
  - holds are judged on current `available`;
  - corrections are checked at every past boundary.
- The trace: T1–T70 cover every normative line of `stage-3.md`.
- The supplied checks: none asserts an exact authorization key set, so `closed_at` breaks none of them.
- W18 is written independently of the implementation.

### Polish (recorded only)

- D73 and 3.14 say a fixed-size snapshot record needs no cap. The size of each record is fixed, but their number is not: every first `GET /statement` stores one, about 250 bytes in the export. A long-lived state's export would eventually pass the 64 MiB import limit, the same class as stage-1 D36. No check comes near it.
- Stage 4 requires that saved statements "remain available in their original form". With snapshots kept as cutoffs, stage 4 must render a stage-3 snapshot's entries in the stage-3 payment form, without stage-4 fields. The export's `schema: 3` tells it which form applies, so stage 3 needs no change.
