<!-- generated from catalog/toolchains.yaml by tools/derive/toolchains_gen.py; do not edit -->
# Toolchains

Every compiler release the project measures, from `catalog/toolchains.yaml`
(`offload/engine/toolchains.py` reads it; `python3 -I tools/derive/toolchains_gen.py` writes this
table, `site/static/toolchains.js` and `tools/jobs/toolchains.sh`). To add a release:
docs/tooling/contributing.md, "Add a compiler or a compiler release".

| id | family | version | machine | GPU | memory modes | lane | table column | site label | role |
|---|---|---|---|---|---|---|---|---|---|
| `afar` | afar | 24.3.0 | tuolumne | gfx942 | copy (0), unified (1) | tuolumne | AFAR | AFAR 24.3.0 | headline; merged key `afar` |
| `cce19` | cce | 19.0.0 | tuolumne | gfx942 | copy (0), unified (1) | tuolumne | CCE 19 | CCE 19.0.0 | headline; merged key `cce` |
| `cce20` | cce | 20.0.2 | tuolumne | gfx942 | copy (0), unified (1) | tuolumne | CCE 20 | CCE 20.0.2 | headline; merged key `cce20` |
| `cce21` | cce | 21.0.3 | tuolumne | gfx942 | copy (0), unified (1) | tuolumne | CCE 21 | CCE 21.0.3 | headline; merged key `cce21` |
| `cce21_4` | cce | 21.0.4 | tuolumne | gfx942 | copy (0), unified (1) | tuolumne | CCE 21.0.4 | CCE 21.0.4 | regression release, compared with `cce21` |
| `afar_g90` | afar | 24.3.0 | tioga | gfx90a | copy (0) | tioga | AFAR gfx90a |  | gfx90a twin of `afar` |
| `cce19_g90` | cce | 19.0.0 | tioga | gfx90a | copy (0) | tioga | CCE 19 gfx90a |  | gfx90a twin of `cce19` |
| `cce20_g90` | cce | 20.0.2 | tioga | gfx90a | copy (0) | tioga | CCE 20 gfx90a |  | gfx90a twin of `cce20` |
| `cce21_g90` | cce | 21.0.3 | tioga | gfx90a | copy (0) | tioga | CCE 21 gfx90a |  | gfx90a twin of `cce21` |
| `afar_mi300x` | afar | 24.3.0 | mi300x | gfx942 | copy (0) | mi300x | AFAR MI300X |  | mi300x twin of `afar` |
| `afar_mi350x` | afar | 24.3.0 | mi350x | gfx950 | copy (0) | mi350x | AFAR MI350X |  | mi350x twin of `afar` |
| `nvhpc` | nvhpc | 25.11 | wingtip | sm_80 | copy (0), managed (2) | wingtip | NVHPC 25.11 | NVHPC 25.11 | headline; merged key `nvhpc` |
| `nvhpc269` | nvhpc | 26.9 | wingtip | sm_80 | copy (0), managed (2) | wingtip | NVHPC 26.9 | NVHPC 26.9 | headline; merged key `nvhpc269` |
| `gcc` | gcc | 16.2.0 | tuolumne | gfx942 | copy (0), unified (1) | gcc | GCC 16.2 | GCC 16.2.0 | headline; merged key `gcc` |
| `gcc_g90` | gcc | 16.2.0 | tioga | gfx90a | copy (0) | gcc | GCC 16.2 gfx90a |  | gfx90a twin of `gcc` |
| `gcc_mi300x` | gcc | 16.2.0 | mi300x | gfx942 | copy (0) | mi300x | GCC 16.2 MI300X |  | mi300x twin of `gcc` |
| `gcc_mi350x` | gcc | 16.2.0 | mi350x | gfx950 | copy (0) | mi350x | GCC 16.2 MI350X |  | mi350x twin of `gcc` |
| `gcc_sm80` | gcc | 16.2.0 | wingtip | sm_80 | copy (0) | gcc | GCC 16.2 | GCC 16.2.0 | headline; merged key `gcc_sm80` |

## Families

| family | name | vendor packet | recipe kind | message table | gate compile budget (s) | legality witness |
|---|---|---|---|---|---|---|
| afar | AMD AFAR | amd | afar | afar | 8 | its front end checks other families' cases |
| cce | Cray CCE | hpe | cce | cce19 | 30 |  |
| nvhpc | NVIDIA HPC SDK | nvidia | nvhpc | nvhpc | 15 | witnesses other families' cases |
| gcc | GNU GCC | - | gcc | gcc | 2 | never (under test only) |

## Lanes

| lane | toolchains | run by |
|---|---|---|
| tuolumne | `afar`, `cce19`, `cce20`, `cce21`, `cce21_4` | the flux (pbatch) scripts, `tools/run_matrix*.sh`, `tools/jobs/run_x0_full.sh` |
| tioga | `afar_g90`, `cce19_g90`, `cce20_g90`, `cce21_g90` | one supervised interactive job at a time, `tools/run_tioga*.sh` |
| mi300x | `afar_mi300x`, `gcc_mi300x` | Slurm jobs on the MI300X nodes (`tools/campaigns/run_matrix.py` per set) |
| mi350x | `afar_mi350x`, `gcc_mi350x` | Slurm jobs on the MI350X nodes (`tools/campaigns/run_matrix.py` per set) |
| wingtip | `nvhpc`, `nvhpc269` | `tools/run_wingtip*.sh` (direct runs inside the cap) |
| gcc | `gcc`, `gcc_g90`, `gcc_sm80` | `tools/jobs/run_gcc_lane.sh`, `tools/jobs/run_gcc_sweep.sh` |
