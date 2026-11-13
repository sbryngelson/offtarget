# tools/review

Independent legality reviews of the findings. A finding's own header argues that its program is legal; a review asks
readers who never see that argument. The records go to `data/findings/reviews/<id>.json` and the verdict shows on the
site and in `offload issues --show`. The rule and the record format are in
[offload/engine/legality_review.py](../../offload/engine/legality_review.py).

| file | holds |
|---|---|
| `review.py` | `select` (the findings of a set), `prepare` (batches for the readers), `ingest` (check the answers, write the records) |
| `instructions.md` | what a reader is told; its version is `INSTRUCTIONS` in the engine module |
| `adjudicate.md` | what an adjudicator of a dispute is told |
| `verify.md` | what a verifier of a reading's premises is told |
| `decoys/` | programs with a known answer (illegal, or legal with a result the specification does not require); `decoys.json` gives each answer |

How a review runs:

1. `python3 -I tools/review/review.py prepare --out DIR` puts each finding in two batches of four. A batch also holds
   one decoy at a random place. A case shows the program without its header, its specification version, how many
   compilers fail and how, and the expected and observed result, with compiler names removed.
2. A reader (a model or a person) works one batch from `DIR/batch-NN/prompt.txt` and writes `out.jsonl`: for each case,
   legal and result_required (yes, no or uncertain), the reasoning and the quoted passages. Running the readers is
   the operator's; nothing here calls a model.
3. `python3 -I tools/review/review.py ingest DIR` checks each batch's decoy and every quote against the specification
   text, and writes the records.

`python3 -I tools/review/review.py disputes --out DIR` then takes the findings whose two readers disagree or are
uncertain. Each case adds both readings, as Reading A and B in random order, and each batch holds a decoy dispute: a
decoy with its right and a wrong reading (`right_reading`, `wrong_reading` in `decoys.json`). The adjudicators answer
the same questions from `adjudicate.md`, and `ingest DIR` records them as adjudicators.

A dispute from outside (the "Dispute or support a finding's legality" issue form) is adjudicated the same way:
`disputes --out DIR --argument FILE ID` pairs the argument in FILE with a counted reading of finding ID. The new
adjudicators join the record's, so one that agrees with the dispute makes the finding contested.

`python3 -I tools/review/review.py verify --out DIR` then fact-checks every reading that counts, whatever it
concludes. A verifier (`verify.md`) lists the premises a reading rests on and marks each holds, false or unsure;
false needs a specification passage or a program line, both checked mechanically. Each batch holds two decoy
readings of a decoy program, one resting on a false premise and one sound (`wrong_reading`, `right_reading`), and
a verifier counts only if it refutes the first and upholds the second. A refuted reading goes to a second verifier;
when two counted verifiers refute it, it no longer counts (`refuted`).

A reader counts only when it read under the current instructions (`INSTRUCTIONS`), caught its batch's decoy, gave
only specification quotes that are in the specification, quoted at least one program line, gave only program lines
that are in the program, and said the program lacks nothing that is there (its `absent` texts; `check_program`). The verdict
follows from the counted readers and adjudicators by a fixed rule: adjudicators decide first (two that find the
program legal and the result required confirm it, one that finds it not legal or not required contests it); without
them, two readers that agree confirm it and a reader that says no contests it. A contest or a doubt that prior art
(such as an OpenMP Examples program) or outside evidence settles is supported. Anything else is unconfirmed. A change to the program (not its header)
makes the record stale and the finding unconfirmed until it is read again.
