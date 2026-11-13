# Setting up a clone

The repository holds the code, the catalog, the findings and every committed generated file. Three kinds of input are git-ignored because they are large, third-party, or measurements. Tests that need them carry a marker and skip, naming the missing paths, so a fresh clone passes the suite. `python3 -I -m pytest -q -rs` lists the skips and their reasons.

| input | marker | used by | how to obtain |
|---|---|---|---|
| `spec/openmp/openmp-{5.0,5.1,5.2,6.0}.pdf`, `spec/openacc/openacc-3.4.pdf` | `needs_spec` | `offload/engine/spec_text.py`: the quotes and page numbers of the rulings registry, the rule and grammar slices, and the offload scope. It extracts the text with `/usr/bin/pdftotext -layout` into `results/spec_cache/`. | Download them from https://www.openmp.org/specifications/ and https://www.openacc.org/specification and save them under these names. |
| `corpus/` (omp_vv, acc_vv, omp_examples, aomp, llvm, gcc, rocm_llvm_afar) | `needs_corpus` | The omp_vv baselines and cross-checks (`offload/engine/ompvv.py`), the offload scope, the triage flags and the corpus index. | Clone each repository with `git clone` and check out the commit listed below into `corpus/<name>`. |
| `results/` | `needs_results` | The measurements (matrix, baselines, fuzz campaigns, expected-value runs), the confirmer's batches and evidence, the support tables, and the tests that check generated files are current ([regenerate.md](regenerate.md)). | Not downloadable. Either rerun the measurements on AMD GPU nodes (steps `measure` to `confirm-evidence` of [regenerate.md](regenerate.md)) or copy a maintainer's `results/` directory. |

## Spec files

The catalog quotes the printed page numbers of these files, so another printing can break the quote tests.

```
53101ade3d1fc91ea8a3885e9a93955543e10a65e681cbb26221dfdf811b1771  spec/openmp/openmp-5.0.pdf
77b11905a86a169ee9da8291c8edd76731639d06ec327eb254e8aa0e2972095c  spec/openmp/openmp-5.1.pdf
3a176ab131d7f83ff525aa5449f0e0880138ab444a69d19b4365f7f318381946  spec/openmp/openmp-5.2.pdf
bcadeebbc13e99a0b7cd4e58099875bd94411d1ae3c7817d5db82968874132db  spec/openmp/openmp-6.0.pdf
119817902dffb89a01510aab90b1fddb8623d92ac4e57aa4db0192ce3088fae1  spec/openacc/openacc-3.4.pdf
```

Check with `sha256sum spec/openmp/*.pdf spec/openacc/*.pdf`.

## Corpus repositories

The omp_vv commit is pinned in `offload.engine.ompvv.UPSTREAM`. `python3 -I tools/regenerate.py --check ompvv-corpus` checks that `corpus/omp_vv` is at that commit and that the omp_vv rows of `data/index/corpus_index.csv` match the checkout. The baselines of the earlier SOLLVE/sollve_vv snapshot (commit d978684) are in `results/archive/ompvv-sollve-d978684/`.

| directory | repository | commit |
|---|---|---|
| corpus/omp_vv | https://github.com/OpenMP-Validation-and-Verification/OpenMP_VV.git | f7d95b34 |
| corpus/acc_vv | https://github.com/OpenACCUserGroup/OpenACCV-V.git | e0d2503 |
| corpus/omp_examples | https://github.com/OpenMP/Examples.git | 3e4757a |
| corpus/aomp | https://github.com/ROCm/aomp.git | fc2dfc1 |
| corpus/llvm | https://github.com/llvm/llvm-project.git | 5d53d8d3 |
| corpus/gcc | https://github.com/gcc-mirror/gcc.git | 9e5dc38 |
| corpus/rocm_llvm_afar | https://github.com/ROCm/llvm-project.git | 3ba19712 |

```bash
git clone https://github.com/OpenMP-Validation-and-Verification/OpenMP_VV.git corpus/omp_vv
git -C corpus/omp_vv checkout f7d95b342b9330ecac735ed31b9fb193d8f60a9b
# do the same for the others; for llvm and gcc a blobless clone is enough:
#   git clone --filter=blob:none URL corpus/NAME
```

## Your machines and compilers

`catalog/machines.yaml` and `catalog/toolchains.yaml` describe hardware (architecture, memory modes) and compilers (family, version, flags). They do not say where a compiler is installed or how to reach a machine. You supply that in a file the tools lay over the catalogs:

1. Copy `catalog/local.example.yaml` to `catalog/local.yaml` (git-ignored) or to `~/.config/offload/local.yaml`, or point `OFFLOAD_LOCAL` at it. `offload.engine.localcfg` documents the rules. Mappings merge key by key, anything else replaces the catalog value, and a null removes it.
2. For a compiler the catalog already lists, set its `install`. This holds a `default` path, optionally an `env` variable that overrides it, and a `fallback` for a second copy. A CCE release uses `module load`, so give its `modules` instead.
3. For a machine the catalog already lists, set `access` and `scheduler`. `access` is `local` or, for a remote machine, `ssh`, `root`, `python` and `run_prefix`. `scheduler` has a `kind` (`flux`, `slurm`, `local` or `direct`), a `queue` and `max_minutes`.
4. For a machine or compiler the catalog does not list, add the entry in the same file with every key that `catalog/machines.yaml` or `catalog/toolchains.yaml` requires. It is checked like a catalog entry. [contributing.md](contributing.md) ("Add a compiler or a compiler release") lists what else a new compiler needs.
5. List legality checkers that are not compilers under test under `independent_checkers`.

`install` says only where a compiler is. Its flags come from its family in `catalog/toolchains.yaml`
(`families.<family>.flags`, by model and language), and they name an offload target. A compiler built without that
target refuses every program before the run starts. GCC, for example, says `GCC is not configured to support
'amdgcn-amdhsa' as '-foffload=' argument`, and `tools/reduce.py` reports `harness error:
unclassified_compile_failure`. To use other flags, override the family in the same file:

```yaml
toolchains.yaml:
  families:
    gcc:
      flags:
        omp: {c: "-fopenmp -foffload=nvptx-none", f90: "-fopenmp -foffload=nvptx-none"}
      latomic: null               # drop the catalog's per-target extra link flags
  toolchains:
    gcc: {install: {default: /usr/local/gcc-16}, env: {}}
```

A toolchain targets one GPU architecture (`arch`), and `--target TOOLCHAIN/MODE` must name one whose architecture is
the node's GPU (otherwise: `wrong_arch: toolchain gcc_sm80 targets sm_80, this node's GPU is gfx942`). A family or
toolchain's `env` (library paths) and `prelude` (commands run before the build, such as `module load`) are the
catalog's machines'; override or clear them (`env: {}`) for your install.

Results from flags other than the catalog's are your machine's: say so in the finding and the pull request. A
program that runs on the host instead (no offload target) is reported as `fell_back_to_host`, which is not a device
result and does not count.

With the file in place, `tools/reduce.py --target TOOLCHAIN/MODE` runs on your machine and writes the rows (recorded result lines) that a finding is built from. [CONTRIBUTING.md](../../CONTRIBUTING.md) describes the contributor path. Without the file the catalogs still load, but a command that runs a compiler stops at the first path that does not exist.

Tests marked `gpu` need a compute node with a supported GPU. The rest of the test suite does not use your machines.

## Example: a remote NVIDIA node (NVHPC 25.11)

The maintainers' A100 node is the machine `wingtip` in `catalog/machines.yaml`. Its `access` entry (ssh host, clone root, python) is in the maintainers' own `local.yaml`. The node has four NVIDIA A100 80GB PCIe GPUs, no scheduler and no GitHub access. NVHPC is at `/opt/nvidia/hpc_sdk/Linux_x86_64/25.11`, and `NVHPC_BIN` overrides that path. Create the environment once:

```bash
python3 -m venv ~/compliant-venv && ~/compliant-venv/bin/pip install -r tools/repo/test_requirements.txt
```

| task | command |
|---|---|
| Copy the tracked and new files, `corpus/omp_vv`, `corpus/acc_vv` and the spec text cache to the clone (`access.root`; `.wingtip_rev` records the revision) | `tools/lanes/wingtip_sync.sh push` |
| Copy the merged result files the expected set is chosen from | `tools/lanes/wingtip_sync.sh push-results` |
| Bring raw results back to `results/nvhpc/raw/` (git-ignored) | `tools/lanes/wingtip_sync.sh pull nvhpc/raw` |
| Merge the raw results into the full result files (new `nvhpc` cells; no AMD row changes) | `tools/campaigns/run_matrix.py replace` |
| Run queues, one per free GPU; one program per GPU via `COMPLIANT_RUN_SLOTS=1`, niced, at most 16 compiles | `tools/jobs/run_wingtip.sh <queue> ...` (options in its header) |
| Run the confirmer against wingtip (`RemoteRunner`) | `tools/confirm.py case ... --toolchain nvhpc --run`, from Tuolumne |
| Run the tests that work there | `python -I -m pytest tests/engine/test_findings.py` |

Only the NVHPC tests run on that node. The full suite runs on the MI300A host. [wingtip.md](wingtip.md) describes the offline jobs.
