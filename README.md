# Dark Factory

A software factory of four coding agents in BAND Desktop, built for the WeAreDevelopers x BAND Dark Factory hackathon (track: pocketful). The band plans, builds, independently verifies and reviews a service one stage at a time. See [FACTORY.md](FACTORY.md) for how it works.

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

Then create a room with all four seats and yourself, and dispatch the run by posting `tasks/run.md` into the room, addressed to the planner. It is the only human input for all four stages. Keep the machine awake, plugged in and online until the planner posts its final report.
