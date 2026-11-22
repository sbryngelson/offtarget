# tools/review

The legality verdicts of the findings. A finding's verdict is computed from mechanical evidence and maintainers'
rulings only (`verdict` in [offload/engine/legality_review.py](../../offload/engine/legality_review.py)); the
evidence is gathered by [offload/engine/legality_mechanical.py](../../offload/engine/legality_mechanical.py):

- the rules engine (`prerun.rules_witness`, at OpenMP 6.0 when 5.2 cannot read a program whose header names 6.0) accepts
  or rejects the program; a result hazard (`prerun.result_hazards`)
  is a checked result the specification does not require;
- a second witness: a toolchain of another family (never GCC) built and ran it correctly in the committed rows, or a
  front end of a family that does not fail accepted it (`catalog/finding_witness.yaml`): AMD's, run on a compute node
  by `tools/jobs/run_mechanical.sh`, or NVHPC's (`catalog/machines.yaml` `independent_checkers`), run over ssh from a
  login node by `review.py mechanical --nvhpc`, or Intel's (`--intel`, a compute node). A front end of the lineage
  of a failing compiler does not count (`LINEAGE`: AMD's clang, CCE's C compiler and Intel's icx share one), nor
  does a correct run of one when the finding is a refusal. A checker that drops a directive with a warning
  ("ignored"), crashes ("ice") or says the feature is not supported ("unsupported", the harness message patterns)
  gives no verdict;
- for a wrong answer, an expected value from another family's run, the program's own check or the generator's model.

Verdicts: `ruled` (a maintainer's ruling that holds), `refuted`, `supported` (outside evidence), `checked`, `open`.

    python3 -I tools/review/review.py mechanical [ID ...]   # recompute the records (every finding without IDs)
    python3 -I tools/review/review.py mechanical --nvhpc    # first run NVHPC's front ends where needed (ssh)
    python3 -I tools/review/review.py mechanical --intel    # first run Intel's front ends (a compute node)
    python3 -I tools/review/review.py queue                 # the open findings, grouped by what is missing

Each record stamps the hash of its inputs (program, outcome, cells, stored front-end rows, verdict code);
`tools/regenerate.py --check` reports the records whose inputs changed. A ruling (below) settles an open finding.

## Advisory readings

The readings below are kept in each record as `advisory` and `advisory_why`. They decide nothing and are not
published; `queue` shows them beside each open finding.

| file | holds |
|---|---|
| `review.py` | `mechanical`, `queue`, `rule`; for the advisory readings `select`, `prepare`, `ingest`, `disputes`, `verify` |
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
that are in the program, and said the program lacks nothing that is there (its `absent` texts; `check_program`). The advisory verdict
follows from the counted readers and adjudicators by a fixed rule: adjudicators decide first (two that find the
program legal and the result required confirm it, one that finds it not legal or not required contests it); without
them, two readers that agree confirm it and a reader that says no contests it. A contest or a doubt that prior art
(such as an OpenMP Examples program) or outside evidence settles is supported. Anything else is unconfirmed. A change to the program (not its header)
makes the record stale and the finding unconfirmed until it is read again.

## A maintainer's ruling

When the readers misread the specification and the passage that decides the question is clear, a maintainer records
a ruling instead of tuning the instructions to that one answer:

    python3 -I tools/review/review.py rule ID --spec openmp-5.2.txt --section 3.2.6 \
        --quote "The values of the iterator are the set of values" --why "k = 1:2 names the one value k = 1 ..."

`--quote` repeats for several passages. The command refuses a quote that is not in the specification under the section
named, and a record whose program changed since its review. The verdict is then `ruled` ("settled by a maintainer's
ruling"): the issue page shows the ruling and its passages. A ruling
lapses with the readings when the program changes (`ingest` drops it), and `problems` reports one whose passages no
longer check out.
