# Room log

The whole run happened in one BAND room, `7884df0c-298f-4120-abce-f6bef24337b9`. Its members were the four seats and the human. The room holds 10,347 events.

## Files

| File | What it is | Events | Covers |
|---|---|---|---|
| `../room.json` | The Band console's **Download full session**, saved unchanged apart from the redaction below | 2,600 | 15:50 to 19:17 UTC on Oct 4: from about 12 minutes into stage 4 (part 4 of the stage-4 handoff) to the end of the run |
| `7884df0c-console-filtered.json` | The Band console's **Download filtered**, with the event types set to messages and system events, saved unchanged | 286 | The whole run: every message from the dispatch at 06:18 UTC to the final report at 18:44 UTC |
| `7884df0c-api.jsonl` | The whole room read page by page from Band's API with `band room messages <room> --json --page N`, after the run | 10,347 | Everything, from the seats joining at 06:17 UTC to the last event at 19:17 UTC |

**Why three files.**
- The console's full-session download of a room this size holds only its most recent 2,600 events. `room.json` is that download, as the participant guide asks, so it starts in stage 4. We have reported this to the BAND team.
- The filtered download is the same console export with tool calls, tool results and thoughts left out. It shows every message the seats and the human wrote, from the dispatch on.
- The API read has every event. Each line is one message object exactly as the API returned it, sorted by `inserted_at`. Its field names are the API's (`sender_name`, `message_type`, `inserted_at`), not the console's. Every event in `room.json` is also in it.

| Event type (API read) | Count |
|---|---|
| `tool_call` | 4,558 |
| `tool_result` | 4,558 |
| `thought` | 945 |
| `text` | 282 |
| `participant` | 4 |

**Text messages by sender:** planner-h6bf 101, verifier-h6bh 85, critic-h6bj 50, builder-h6bg 45, Dileepa Balasuriya 1 (the dispatch).

**The 45 events after the final report** (18:44:15 to 19:17 UTC) are the seats' last tool calls, tool results and thoughts.
- In the first minute, the planner closed the room's work items and stopped its timer. It also wrote one last memory note (`lessons/planner-times-from-the-clock.md`, 18:44:48 UTC) and checked the repository.
- Then the seats re-armed their room watches and checked their inboxes until the human closed their terminals.
- None is a message.

## One redaction

The seats' tool calls carry the ids of their Band receiver leases (`jrx_…`). The participant guide says to replace a credential in the room log with `[REDACTED]`. Each lease id is written as `jrx_[REDACTED]` in `room.json` and `7884df0c-api.jsonl`. The filtered download holds none. Nothing else was changed.

## Finding the evidence

- **The dispatch:** the only `text` message from `Dileepa Balasuriya`, at 06:18:19 UTC on Oct 4. It is in the filtered download and the API read.
- **Stage reports and the final report:** `text` messages from `planner-h6bf` that start with `STAGE N REPORT` or `FINAL REPORT`. The final report is at 18:44:11 UTC.
- **Verdicts:** `text` messages that start with `VERDICT` (critic-h6bj) or carry `PASS` (verifier-h6bh), each naming a full commit hash.
