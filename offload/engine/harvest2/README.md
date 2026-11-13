# offload/engine/harvest2

This package takes Fortran and C OpenMP offload and OpenACC programs from further public sources. It converts them to the form of `offload.engine.harvest.convert` and splits them into a development set and a holdout.

The entry point is `tools/campaigns/harvest2.py`, including its `hand` subcommand.

It reads cloned sources under `corpus/` and `catalog/harvest2_hand.yaml`. It writes converted programs with provenance.

- `aomp.py` ROCm/aomp suites beyond `test/smoke` and `test/smoke-fails`.
- `examples.py` the OpenMP Examples repository (examples tagged run and success).
- `gomp.py` the GCC libgomp testsuite (libgomp.c, libgomp.fortran, libgomp.oacc-*).
- `hand.py` training material and applications made self-checking by recorded edits.
- `split.py` splits the programs. The holdout is the lowest 30% of the sha256 space of a program's code.

Read `split.py` first, then one source module.
