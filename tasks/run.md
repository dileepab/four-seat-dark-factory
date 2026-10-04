@<planner handle> You are the lead seat for our factory. Build all four stages of the pocketful track, one after another. Finish each stage completely, including its stage report, before you start the next one, and keep every stage in its own complete, buildable folder.

Track: pocketful
Result repository: /Users/Dileepa/dark-factory-v3
Specifications (read each in full when its stage starts, and paste the text each seat needs into its handoff):
  Stage 1: /Users/Dileepa/df-spec/pocketful/spec/stage-1.md
  Stage 2: /Users/Dileepa/df-spec/pocketful/spec/stage-2.md
  Stage 3: /Users/Dileepa/df-spec/pocketful/spec/stage-3.md
  Stage 4: /Users/Dileepa/df-spec/pocketful/spec/stage-4.md
An earlier stage's specification still applies to everything a later stage does not change.

Stage folders: /Users/Dileepa/dark-factory-v3/stage-1/ to stage-4/. Stage 1 starts empty. Each later stage starts as a copy of the stage before it (scripts/new-stage.sh N) and widens that copy to its own specification. Never edit an accepted stage's folder, and never put a later stage's requirements into an earlier folder.

Supplied checks, a partial sample of each stage's graded suite (read them to wire the service up; never write code to them): /Users/Dileepa/df-spec/pocketful/test/stage_1/ to stage_4/. They ship about 79%, 35%, 9% and 16% of the graded checks for stages 1 to 4; every graded check is written in the specification.

Check command for stage N (use a new --out directory every time):
  /Users/Dileepa/dark-factory-v3/scripts/harness.sh run --track pocketful --repo /Users/Dileepa/dark-factory-v3 --stage N --out /Users/Dileepa/dark-factory-v3/.work/checks/sN-<nn>
Final check for stage N, the mode it is graded in (no outbound network, 2 vCPU, 2 GiB):
  /Users/Dileepa/dark-factory-v3/scripts/harness.sh run --track pocketful --repo /Users/Dileepa/dark-factory-v3 --stage N --mode isolated --out /Users/Dileepa/dark-factory-v3/.work/checks/sN-final-<nn>
The target line for stage N is `claimed stage: N`. For stages 1 to 3 the next stage's suite also runs as an overshoot probe and must fail: a stage folder must not solve the stage after it.

From stage 2 on the service has a browser UI. It is judged on its own: coherent, presentation-ready, responsive at phone and desktop widths, and clear in every state the specification names, over code another developer could maintain.
Each stage folder needs a Dockerfile and a RUN.md, and the image must contain everything the service needs at run time.

This run is unattended: this message is the only human input for all four stages. Post a stage report in the room at the end of each stage, and a final report when stage 4 is done.
