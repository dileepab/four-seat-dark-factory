# Dark Factory

A software factory of four coding agents in BAND Desktop, built for the WeAreDevelopers x BAND Dark Factory hackathon.

- **Team:** Dileepa Balasuriya, solo (lablab team "dileepa-dark-factory")
- **Track:** pocketful
- **Stage reached:** 4 of 4, in one unattended run from a single dispatch, in one room

The band plans, builds, independently verifies and reviews a service one stage at a time. Start with [FACTORY.md](FACTORY.md): how the factory works, what the submitted run cost, and what it caught.

## Layout

| Path | What it is |
|---|---|
| `FACTORY.md` | The factory: seats, design choices, measured time and cost, how it catches bad work, and how it got here |
| `PROTOCOL.md` | The room protocol every seat follows |
| `mandates/` | One mandate per seat, named after the seat's handle in the room. Generic: they name nothing about the product |
| `CLAUDE.md` | Tells every seat to load the protocol and its mandate |
| `tasks/run.md` | The exact dispatch: the only human input to the run, for all four stages |
| `stage-1/` ... `stage-4/` | One complete, buildable service per stage. Each has a `Dockerfile`, `RUN.md`, `PLAN.md` (the planner's plan and decisions), `REVIEW.md` (the critic's entries), an acceptance suite and builder tests. All of it was written by the band |
| `room.json` | The Band console's full-session download of the run's room |
| `rooms/` | The same room read in full from Band's API, unchanged. See [rooms/README.md](rooms/README.md) |
| `lessons/` | The seats' own notes (Claude Code auto-memory) from this run, copied unchanged |
| `scripts/` | `new-stage.sh`, `harness.sh`, `check-offline.sh`, `check_mandates.py` |

## Running a stage

Each stage folder builds and runs on its own. Follow its `RUN.md`, or from the repository root:

```bash
docker build -t stage-4 stage-4
```

```bash
docker run --rm -p 8080:8080 stage-4
```

## Starting the band

Open four terminals in this folder, one per seat. Each seat gets its role as its git identity, so every commit names the seat that made it:

```bash
GIT_AUTHOR_NAME=planner GIT_AUTHOR_EMAIL=planner@seats.invalid GIT_COMMITTER_NAME=planner GIT_COMMITTER_EMAIL=planner@seats.invalid CLAUDE_CODE_AUTO_COMPACT_WINDOW=500000 claude --model opus --effort max --permission-mode auto "/jam as planner"
```

```bash
GIT_AUTHOR_NAME=builder GIT_AUTHOR_EMAIL=builder@seats.invalid GIT_COMMITTER_NAME=builder GIT_COMMITTER_EMAIL=builder@seats.invalid CLAUDE_CODE_AUTO_COMPACT_WINDOW=500000 claude --model opus --effort xhigh --permission-mode auto "/jam as builder"
```

```bash
GIT_AUTHOR_NAME=verifier GIT_AUTHOR_EMAIL=verifier@seats.invalid GIT_COMMITTER_NAME=verifier GIT_COMMITTER_EMAIL=verifier@seats.invalid CLAUDE_CODE_AUTO_COMPACT_WINDOW=500000 claude --model opus --effort xhigh --permission-mode auto "/jam as verifier"
```

```bash
GIT_AUTHOR_NAME=critic GIT_AUTHOR_EMAIL=critic@seats.invalid GIT_COMMITTER_NAME=critic GIT_COMMITTER_EMAIL=critic@seats.invalid CLAUDE_CODE_AUTO_COMPACT_WINDOW=500000 claude --model opus --effort max --permission-mode auto "/jam as critic"
```

Then set up the room:
1. Create a room with the planner in it.
2. Invite the three parked seats (`band invite`).
3. Add yourself: `band --as <planner handle> chat add <room id> <your handle>`.
4. Check that every seat's `band --as <handle> status` shows the same room.

Then dispatch the run by posting `tasks/run.md` into the room, addressed to the planner. It is the only human input for all four stages. Keep the machine awake, plugged in and online until the planner posts its final report.

## Checking the submission

```bash
scripts/harness.sh check /path/to/clone --track pocketful
```

```bash
scripts/harness.sh run --track pocketful --repo /path/to/clone --all --mode isolated --out /tmp/df-check
```

```bash
python3 scripts/check_mandates.py
```
