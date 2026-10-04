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

## W14, W15, W16, W17 @ 0acff74 (one review, D87): BLOCKED

- Product: `0acff74a4c06953d198fe48a9731271333372c3d`, the builder's one HANDOFF of W14 to W17 (parts 1 and 2).
- Suite: `b4f6d160e90775f19f99c325b43bdc5add21d2d3`. The verifier posted PASS at 0acff74 with it: "2586 passed", nothing deselected. I also ran the first suite, f5df9a1.
- Plan: 350c7c6, which is f745388 plus W18.7.

| Item | Verdict | Rules no test checks (mutants that survive the suite) |
|---|---|---|
| W14 | BLOCKED | G16 exact comparison of trailing fraction zeros; Q04 a broken percent-escape is 422; V03 `closed_at` of a clock-expired hold is `expires_at` as stored |
| W15 | BLOCKED | T05 ties in code-point order |
| W16 | BLOCKED | K12 movements at one instant combined in either creation order; K25b no tolerance on `effective_at` below one second |
| W17 | BLOCKED | E14 snapshot cutoff; E16 base plus capture payments; E26 W18.7 (a): a display-only link counted on the stage-2 path |

- Reason: 0acff74 meets the plan in everything I probed, and I found no product defect. But for nine rules, a one-line change in a scratch copy breaks the rule and every W14 to W17 test still passes ("546 passed"; for E26, the export and upgrade files: "32 passed"). Each change is proven observable: a probe passes on 0acff74 and fails on the mutant.
- Missing evidence: a suite commit with a test that fails on each of the nine changes below (verifier). No product change is needed. On that commit I rerun the nine survivors; earlier results carry over (PROTOCOL, "When the verdict commit moves").

### The plan review is closed

f745388 resolved every point of the plan review above:
- point 1: D84, I67, the schema-3 base and capture ids, and the schema-2 capture records;
- point 2: D85 and I61;
- point 3: D86;
- point 4: D72, revised for a future `from`;
- point 5: I50 "earlier than", and W14.1 "strictly later";
- point 6: 3.9 "the requested page", and D72 naming `known_at`;
- point 7: B1 to B5 in W14.1, W14.6, W14.7, W15.1 and W16.9.

The two polish items stay recorded only.

### What I checked

1. **Clause map.** Every rule of plan 3.2 to 3.11 for W14 to W17 maps to the code that enforces it:
   - `instant.ts`: grammar and exact keys;
   - `context.ts`: decoding and first occurrence;
   - `handlers/me.ts`: views, echo, the stage-2 body;
   - `history.ts`: `holdIn` and the overdraft sweep;
   - `views.ts`: `closed_at`;
   - `fixture.ts`: seeded times, D85, the seeded base;
   - `handlers/statement.ts`: windows, order, paging, snapshots;
   - `handlers/corrections.ts`: steps 1 to 14;
   - `snapshot.ts`: schema 3, imports of schemas 1 to 3, D84, D86;
   - `state.ts`: the clock and issued times.

   No clause lacks code.
2. **Probes against a local 0acff74** (`.work/critic-h6bj/probe_*.py`), all passing:
   - `probe_w14.py`: 94 checks, among them instants, B1, B2, B5, I50, I61, I67, D85 and ties;
   - `probe_w15_17.py`: statements, corrections and exports, plus upgrades from the frozen stage-1 and stage-2 builds;
   - `probe_gaps.py`, `probe_k25.py` and `probe_e26.py`, written for the survivors below.
3. **Mutation.** I wrote 122 small mutants of the new code, most of them one line. Each ran in a scratch copy (`.work/critic-h6bj/mutS3_*`) on two local servers, against my own frozen stage-1 (port 18354) and stage-2 (port 18353) builds. Runner: `rerun_s3.py <0acff74 stage-3> <suite acceptance> <plan> 0`, with `--upto 17 -m "not container"`.
   - I counted a kill only when a failure message named the mutated rule.
   - K25 crashed with 500, from a scope error in my edit. K25b replaces it, which leaves 121 mutants.
   - E06 and E16 first failed only on 401s from a frozen service that parallel workers shared. Both were rerun serially.
   - The timing races in f5df9a1 failed under unrelated mutants too, so I did not count them. The verifier fixed them in b4f6d16.
   - 112 mutants are killed for their reason:
     - the W18.7 tests kill E06 (a), E24 and E27 (b);
     - the I67 checks kill R04, a view that takes T from `known_at`. The W18.7 (c) teardown kills it on its own: on `test_w15_statements.py` alone, "I67 violated after the test on A: ada GET /me (10000, 10000, 9995, 5) != known_at far future (10000, 10000, 10000, 0)".
   - 9 survive.
   - On b4f6d16, a clean run of the eight W14 to W17 files gives "546 passed".
4. **Atomicity and error paths.**
   - A correction runs from its checks to its commit in one synchronous callback inside `idempotent()`.
   - A first statement read stores its snapshot in the same step.
   - An import validates a fresh state before it replaces the old one.
   - The suite's "changes nothing" tests pass for resets, imports and every correction refusal.
5. **Special-casing and network.**
   - No fixture identifier, sample date or expected value appears in `src/`.
   - The only network code is the `node:http` server.
6. **RUN.md and earlier stages.**
   - RUN.md gives build, run, `npm test`, the suite with its prerequisites and `--stage 3` (W17.5).
   - The verifier's run passed the stage-1 and stage-2 regression, the container checks and the supplied checks for stages 1 to 3.
7. **W18.7 at b4f6d16.**
   - (b) and (c) are met:
     - E24 and E27 die in `test_a_partly_captured_hold_round_trips_with_its_history`;
     - R04 dies at the I67 teardown.
   - (a) is not met: E26 survives, see survivor 9.

### Survivors: the change, the run that still passes, and the missing test

Each survivor below has "546 passed" on b4f6d16 unless stated. The runs are in `log_s3_p3.txt` and `log_s3_p4.txt`.

1. **G16, plan 3.4 and D66: exact comparison.**
   - Change: `src/instant.ts`, `fraction.replace(/0+$/, '')` becomes `fraction`, so trailing fraction zeros count and `.500` sorts after `.5`.
   - Why the suite misses it: every test puts the extra digits on the query side, where an inclusive comparison hides the difference.
   - Missing test, with the extra zeros on the record:
     - seed `p_first` at `2026-01-01T00:00:00.500Z` and `p_second` at `2026-01-01T05:30:00.5+05:30`;
     - the feed is `[p_second, p_first]`: one instant, so the later-created comes first;
     - `GET /me?as_of=2026-01-01T00:00:00.5Z` includes both payments.
   - My probe `TIES` on the mutant: `['p_first', 'p_second']`, and a balance of 10001 instead of 10000.
2. **Q04, plan 3.2, 3.4 and I53: a value that does not percent-decode is 422.** The builder's handoff states this.
   - Change: `src/context.ts`, `rawParam` returns `undefined` (absent) instead of `null` (invalid) on a decode failure.
   - The mutant answers the present view to a client that asked for history.
   - Missing test: `GET /me?as_of=%ZZ` and `GET /me?known_at=%ZZ` give 422 `validation_failed`; so do `from`, `to` and `known_at` on `GET /statement`.
   - Probe `D79` on the mutant: `(200, None)`.
3. **V03, I61: a clock-expired hold's `closed_at` is `expires_at` exactly as stored.**
   - Change: `src/views.ts` renders the deadline's millisecond `+00:00` form instead of the stored string.
   - Why the suite misses it: its only case writes the deadline in the service's own form (`shifted(..., digits=3)`, `+00:00`), so both answers agree.
   - Missing test: seed an open hold with `expires_at` `2020-06-15T10:20:30.123456+05:30`. It reads `status: expired` and `closed_at` exactly that string.
   - Probe `SEEDEXP` on the mutant: `2020-06-15T04:50:30.124+00:00`.
4. **T05, plan 3.9 and D72: ties by `payment_id` in code-point order.**
   - Change: `src/handlers/statement.ts`, `byCodePoint(a.payment.id, b.payment.id)` becomes `(a.payment.id < b.payment.id ? -1 : 1)`, which is UTF-16 code-unit order.
   - Why the suite misses it: `test_ties_sort_by_payment_id_code_points` uses ASCII ids only, where the two orders agree.
   - Missing test: add `p_ｚ` and `p_\U0001F600` to that test's ids, all at one `created_at`. Code-point order (Python's `sorted`) puts `p_ｚ` first; UTF-16 puts the emoji first.
   - Probe `S5` on the mutant: `['p_B', 'p_a', 'p_b', 'p_😀', 'p_￿']`.
5. **K12, I58 and W16.8: movements at one instant are combined before the check.**
   - Change: `src/history.ts` makes the overdraft check after every event instead of after each instant.
   - Why the suite misses it: the sweep takes one instant's events in creation order. The suite's case (`spent`) moves a debit onto a credit that was created earlier, which passes either way.
   - Missing test, with the debit created first:
     - Dee's opening balance is 300. Dee pays Cy 300, then Ada pays Dee 500.
     - Dee corrects her payment to 500 with `effective_at` = Ada's payment's `created_at`. That is 201.
     - Dee's `total` at that instant is 300.
   - `probe_gaps.py` on the mutant: 409 `historical_overdraft`.
6. **K25b, plan 3.5 and D81: no tolerance on `effective_at`.**
   - Change: `src/handlers/corrections.ts` validates against `msKey(now.ms + 500)`, a half-second tolerance.
   - Why the suite misses it: `test_effective_at_later_than_now_is_422` starts at one second ahead.
   - Missing test, one level below that:
     - take a fresh service time mark and send a correction with `effective_at` 200 ms after it. Expect 422.
     - If a slow host makes it 201, the revision's `recorded_at` must not be earlier than its `effective_at`. An accepted correction always has `effective_at` ≤ now ≤ `recorded_at`, so this check holds on a correct product.
   - `probe_k25.py`: 0acff74 refuses the correction at 300, 200 and 100 ms ahead. The mutant answers 201 with `effective_at` `…51.631000Z` and `recorded_at` `…51.332+00:00`.
7. **E14, plan 3.11: a snapshot cutoff beyond the state's creation sequence is invalid.**
   - Change: `src/snapshot.ts`, `check(x.cutoff <= seq, …)` becomes `check(true, …)`.
   - W17.4's cases in the suite stop at the snapshot's owner.
   - Missing test: in `test_rejected_schema_3_import_changes_nothing`, raise one snapshot's `cutoff` above the state's largest `seq`. Expect 422 and the export unchanged.
   - `probe_gaps.py` on the mutant: 204.
8. **E16, plan 3.11 ("full validation") with D84 and I67: a schema-3 hold's `base_captured_amount` plus its capture payments equals its `captured_amount`.**
   - Change: `src/snapshot.ts`, `check(captured === a.captured_amount, …)` becomes `check(true, …)`.
   - An accepted state where they differ breaks I67 for that hold: `GET /me` holds `amount − captured_amount`, while the history holds `amount −` (base + captures).
   - Missing test: raise one hold's `base_captured_amount` by 1 in an export. Expect 422 and the export unchanged.
   - Probe `E4` on the mutant: 204.
9. **E26, W18.7 (a) and D84 on the stage-2 import path: a display-only link counts nothing.**
   - Change: `src/snapshot.ts`, in the schema-2 import, before `for (const [id, paymentIds] of captures) {`, add every existing payment named in a hold's `payment_ids` to its captures.
   - On the export and upgrade files: "32 passed".
   - Why the new test misses it:
     - the frozen stage-2 build ignores a seeded `created_at`, so the hold and its seeded link both carry the reset's instant;
     - a link counted at its own time then equals base captured from creation;
     - so a link-counting import is visible only when the link is larger than the base.
   - Missing test: in `test_stage_2_partly_captured_hold_and_display_only_links`, make `p_link` 450 instead of 50, with the seeded `captured_amount` 400 and the API capture 100. Then:
     - the import is 204 (I37);
     - 600 is held from the hold's creation and 500 from the capture.
   - `probe_e26.py`: 0acff74 gives 204, 600, 500. The mutant answers 422 "its capture payments exceed its captured_amount". A link-counting import that clamped the base at 0 would hold 550 at the creation instead.

### Checked and fine

- Everything else in W14 to W17 that I probed, mutated or read: instants and their grammar (G01 to G15), echo and decoding (Q01 to Q03, R01 to R06), historical holds and B1 and B2 (H01 to H15), seeded times and opening balances (X01 to X09), issued times and order (S01 to S03), `closed_at` (V01, V02), statements (T01 to T22 apart from T05), corrections (K01 to K34 apart from K12 and K25), and export and import (E02 to E27 apart from E14, E16 and E26).
- The verifier's evidence for W17.5 (RUN.md), the offline build and the supplied checks.
