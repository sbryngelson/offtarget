# Tests

Run this from the repository root:

    python3 -I -m pytest -q -n auto -m "not gpu"

`-n auto` needs pytest-xdist (`tools/repo/test_requirements.txt`). The suite is about 5700 small checks. It takes some 15 minutes on one core and a couple of minutes on sixteen. Without xdist, run the folder you changed. `-m "not slow"` leaves out the 121 tests that build the site data or the data bundle, install the package or compare committed files with measurements. The `check` workflow runs all of them.

`pytest.ini` puts the root and `tests/` on the path. Add `-rs` to list the skips. Tests marked `gpu` need a GPU on the node and run by default, and `-m "not gpu"` leaves them out. Do not run compilers or tests on login nodes.

The full lane copies the tree to the A100 host and runs the suite there with xdist, using `tools/lanes/wingtip_offline.sh tests [FILE...]`. The test ids it leaves for Tuolumne are listed in the run's `tuolumne.txt`, and `tools/lanes/run_tioga_suite.sh` runs most of them on Tioga. `docs/tooling/contributing.md` and `docs/tooling/wingtip.md` give the details.

| folder | tests |
|---|---|
| `confirm/` | the confirmer: collectors, legality gate, triage, drafted findings |
| `site/` | the site build and its checks, the site data, the dashboard |
| `bench/` | the benchmark sets, harvesters and sealed hold-outs |
| `dataenv/` | the data-environment rules and generator |
| `cluster/` | campaigns, gate, toolchain catalog, regeneration, lane scripts, standing rules |
| `engine/` | the generators and the rest of `offload/engine/` |

A suffix on a test file says where it can run besides the A100 host (`tools/lanes/tioga_suite.py`):

- `_afar` needs AFAR's front end.
- `_nogpu` runs with the GPU hidden.
- `_gpu` builds for and runs on the device.
- `_inputs` reads git-ignored inputs.
- `_web` needs node and Chrome.
- `_sealed` reads the unscored sealed sets.
- `_skips` skips by design.

Files without a suffix stay on the MI300A host.

The files directly in `tests/` cover the two commands, the package bundle, the top-level layout and the documentation references.

`tests/data/` holds small inputs the tests read: sample programs, control programs, fake toolchains, fuzz and message samples, and audit summaries.

The tests read a made-up user's machines and lanes (`tests/data/local_settings.yaml`), not yours. The tests that run a real compiler need its install path. Put your own settings file (based on `catalog/local.example.yaml`) in `OFFLOAD_TEST_LOCAL`.

Tests that need git-ignored inputs carry `needs_spec`, `needs_corpus("name")` or `needs_results("path", ...)`. Tests that need the benchmark sets, an old commit or an installed compiler carry `needs_bench("path", ...)`, `needs_commit("rev")` or `needs_compiler("toolchain")`. Tests that use Linux process control (`/proc`, `setsid`, GNU `time`) carry `needs_linux("what")`, and the base-language checks that need GNU gcc as `gcc` carry `needs_gcc`. `conftest.py` skips them and names what is missing. A test with no marker that fails only because a file under `spec/`, `results/` or `corpus/` is absent is reported as skipped in the same way. The tests that `tools/lanes/wingtip_offline.yaml` leaves for an AMD GPU node (`tuolumne_tests`) skip on a machine without the AFAR compiler or with another GPU. `docs/tooling/setup.md` says how to obtain the inputs.
