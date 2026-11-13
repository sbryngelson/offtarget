# Nested pointer-linked data: the campaign generator

Real C and Fortran codes map more than flat arrays: structures that hold pointers to structures, arrays of structures with pointer members, linked lists and trees of fixed depth, pointers to pointers, structures that two parents share, pointers that alias, and in Fortran derived types with pointer and allocatable components nested two or three levels, arrays of such types, pointers to them, and derived-type function results. The nested campaign generates programs for these shapes. This page lists its axes and, for each axis value, the rule that makes a program legal or illegal and what the program shows. The derived-type and OOP campaign covers type-bound procedures, polymorphism, parameterized types, finalization and reductions and is not repeated here.

| Part | Location |
|---|---|
| Shapes, plans, legality model, sampling (`simulate`, `validate`, `program`, `pilot`, `coverage`) | `offload/engine/nested_gen.py` |
| Source text of a program from a shape, a plan and the expected values | `offload/engine/nested_emit.py` |
| Spec rows each program stresses (`rows_for`) | `offload/engine/nested_cites.py` |
| Campaign registration (languages, models, toolchains, doc) | `offload/engine/campaigns/nested.py` |
| Command line | `tools/campaigns/nested.py` |
| Tests | `tests/engine/test_nested_oop.py` |
| Output | `results/nested/<name>/` |

Pages and lines cited below are the printed ones of `results/spec_cache` (OpenMP 5.2, 6.0, OpenACC 3.4). `tests/engine/test_nested_oop.py` checks every citation against the spec text.

## 1. How a program is built

A program is the product of three independent parts.

* **Shape**: the objects the host builds and how they point to each other. Every object has a scalar `s`, a data
  array `a` of eight integers and, per type, links to objects of the next level. The shape is a graph, not a
  tree: an object can have two parents (shared child) and two data pointers can name one array (alias).
* **Kernel**: what the device does to every object reachable from the root, visiting each path of the graph in
  depth-first order. A serial kernel (`target`/`serial`) reads and writes the scalar and the array of every
  object; a parallel kernel (`target teams distribute parallel for`, `parallel loop`) runs a loop over the array
  index with a reduction, one element per iteration, and leaves the scalars alone.
* **Plan**: the data-mapping constructs that make the shape visible to the kernel: one `target` with every list
  item, `target enter data`/`exit data`, `target data`, nested `target data`, `declare mapper`, `target update`,
  OpenACC `copyin`/`copy`/`create`, `attach`, `detach`, structured `data`.

The expected output is computed by `offload.engine.nested_gen.simulate` from the shape and the kernel alone, so it is
the same for every legal plan: `tot` (a sum the device computes, reading values through the pointers) and, per
depth, `ha<L>` and `hs<L>` (the sums of the arrays and the scalars the host reads back through its own pointers
after the plan has ended). Reading back through the host pointers also proves that mapping did not leave device
addresses in the host structure (OpenMP 5.2 §5.9 p.166 l.5-7; OpenACC 3.4 §2.6.4 p.43 l.1451-1453).

A role gives the direction of a mapping group, which is a struct block, the objects contained in it and the arrays
its pointer members point to. The role `in` means the device reads (map `to`/`copyin`). The role `inout` means it
reads and writes (`tofrom`/`copy`). The role `out` means it only writes (`from`/`copyout`), and the host copy is a
sentinel. The values are small integers, so every sum is exact. Every expected value holds in copy and in unified
memory, because the program never relies on a write to a `to`-mapped item staying on the device.

## 2. Axes and the rule behind each value

### 2.1 Language and model

| value | notes |
|---|---|
| C11, OpenMP 5.2 | the base language of most real codes; structure elements and array sections are the list items (5.2 §5.8.3 p.151 l.13) |
| Fortran, OpenMP 5.2 | derived types; allocatable components are deep-copied by the predefined default mapper (5.2 §5.8.2 p.150 l.2-4), pointer components only when listed |
| C11, OpenACC 3.4 | the pointee of a pointer member is never copied with the struct (3.4 §2.7.1 p.49 l.1708-1710) |
| Fortran, OpenACC 3.4 | allocatable and pointer members are not copied with the derived type (3.4 §2.7.1 p.50 l.1711-1713) |

The toolchains are AFAR (OpenMP only), CCE 19/20/21/21.0.4 (OpenMP; OpenACC for Fortran only), NVHPC 25.11 and 26.9
(both models, both languages) and GCC 16.2 (both). The memory modes are copy (XNACK 0, `-gpu=mem:separate`) and
unified (XNACK 1, managed). Cells that a toolchain cannot express (C OpenACC on CCE, OpenACC on AFAR) are not run.

### 2.2 Topology, depth and links

| axis | values | rule and observable |
|---|---|---|
| topology | chain; linked list (one self-referential type); complete binary tree (two pointers per node); diamond (a leaf two parents point to); twin (two pointers of one object to one target); alias (two data pointers to one array); alias-sub (a pointer into the middle of another's array) | shared storage: see 2.4 |
| depth | 1 to 4 levels | `ha<L>`, `hs<L>` per level localize a failure |
| link kind, C | `embed` (struct member), `arr` (array of two structs), `ptr` (pointer to struct), `parr` (pointer to two contiguous structs), `ptrs` (array of two pointers to structs), `pp` (pointer to a pointer array) | `embed` and `arr` are contained in the parent's storage; the others are separate blocks reached by an attached pointer |
| link kind, Fortran | `embed`, `arr`, `ptr` (pointer component), `alloc` (allocatable scalar component), `aarr` (allocatable array of derived type), `parr` (pointer array of derived type) | in OpenMP `embed`, `arr`, `alloc`, `aarr` are contained (deep copy); `ptr` and `parr` are separate. In OpenACC only `embed` and `arr` are contained |
| data member | C: fixed array, pointer to array. Fortran: fixed, pointer, allocatable | a pointer (or, for OpenACC, allocatable) member's array is its own block with its own attach |
| NULL members | a link of one level is NULL / unassociated / unallocated (the last child of a `ptrs`/`pp` link) | the struct copy carries the NULL; the kernel guards on it; OpenACC attach of a NULL pointer leaves it NULL (3.4 §2.7.2 p.51 l.1782-1783). A NULL pointer is never listed in an OpenMP map clause |
| root storage | local struct, heap struct, global struct (`declare target`) | a heap root is an implicitly mapped pointer (5.2 §5.8.1 p.148 l.29-31, §5.8.6 p.160 l.22-31); a local struct is a non-scalar, implicitly `tofrom` (p.149 l.4-5); a declare-target root is always present and needs `target update` for its host values |

### 2.3 Mapping plans

| plan | OpenMP rule | OpenACC rule |
|---|---|---|
| `one`: every list item on the kernel's own construct, in top-down, bottom-up or shuffled order | pointer attachment is decided by the construct's effective map clause set: 6.0 §7.9.6 p.284 l.8-10 ("after all mappable storage blocks are mapped"); 5.2 §5.8.3 p.152 l.5-7. The order of the items is irrelevant | data clauses on a compute construct; attach actions follow the transfers of the same directive (3.4 §2.7.2 p.52 l.1785-1786) |
| `enter`, top-down: `target enter data` per level, kernel without map clauses, `exit data` in reverse | the pointer is attached by the construct that creates its target while its holder is present (5.2 §5.8.3 p.152 l.5-14); the kernel's implicit pointer is translated by lookup (§5.8.6) | `enter data copyin` of the pointer's target attaches it when the holder is present (3.4 §2.7.8 p.55 l.1902-1903) |
| `enter`, bottom-up | a block mapped before its holder is attached only by the construct that creates the holder and lists the pointer's target again (the pointer is "created" then) | an `attach` clause for each pointer once both ends are present (3.4 §2.7.13 p.59 l.2043-2044); `detach` at exit (§2.7.14 p.59 l.2058) |
| `tdata` / `tdata_nested`: `target data` (one, or one per level), kernel with no map clause | the same attachment; the kernel's pointers are firstprivate and are looked up in the mapped address ranges | structured `data` construct; `present(root)` on the compute construct |
| `present`: `enter data`, then the kernel maps every item with `present` | `present` on an item that is not mapped is runtime error termination (5.2 §5.8.3 p.152 l.25-27) | n/a |
| `always`, `close` | `always` copies again even when the reference count is above one, and must not disturb attached pointers (5.2 §5.8.3 p.153 l.15-17, p.154 l.2-5; §5.9 p.166 l.5-7); `close` is a hint (p.155 l.12) | n/a |
| `update`: `enter data alloc`, `target update to`, kernel, `target update from`, `exit data delete` | motion clauses move the list item's target; attached pointers keep their values (5.2 §5.9 p.165 l.28-31, p.166 l.5-7) | omitted: an update of a composite variable with attached pointers is undefined (3.4 §2.6.8 p.48 l.1637-1639) |
| `mapper`, `mapper_enter`: one `declare mapper` per type, one root list item | map-type decay (5.2 §5.8.8 p.163 l.18-19), mappers apply to the clauses of a mapper (p.164 l.1-2); a mapper of a self-referential type is a cycle: unspecified (p.164 l.9-10) | n/a |
| global root | `declare target` variable: infinite reference count, so `map(to:)` copies nothing; the host values travel with `target update` | n/a |

### 2.4 Shared storage: when a program is illegal or has no plan

* **Two list items that name one block in one construct** are illegal (5.2 §5.8.3 p.156 l.6-7).
  Examples are a shared child listed through both parents and two aliasing arrays listed together. The generator maps such shapes in successive
  constructs instead, and a mutation that lists both at once is an illegal negative.
* **A pointer is attached only by a construct that creates its holder or its target** (5.2 §5.8.3 p.152 l.5-7).
  A second parent of a shared child is therefore created *after* the child, by a construct that lists its pointer
  again. Two pointers of one object to one target (`twin`) have no such construct: the plan is infeasible and the
  program is an illegal negative. Real code does this often, so what each compiler does with it is recorded.
* **Aliasing arrays**: a pointer into the middle of an array already mapped is mapped later with a section inside
  the mapped one (5.2 §5.8.3 p.156 l.19-22 requires all or none of a list item to be present). The aliasing
  kernel is serial because elements `i` and `i+2` of one array would race.

### 2.5 Fortran rules that restrict plans

* A pointer component listed in a map clause maps its target only when it is not the base pointer of another
  list item of the same construct (5.2 §5.8.3 p.152 l.1-3; 6.0 §7.9.6 p.282 l.17-19 makes the target
  attach-ineligible). A pointer to a derived type and a pointer member of its target on one construct is
  therefore unspecified, while level-by-level constructs are defined. The generator classifies the single-construct
  forms `unspecified` (observations).
* A pointer's target mapped in parts (a member first) and then whole violates p.156 l.19-22. Fortran bottom-up
  mapping of pointer chains is therefore `unspecified`, while C bottom-up (the member is an array elsewhere) is defined.
* In a type reached by the predefined default mapper, pointer components are treated as undefined unless listed
  and allocatable components are deep-copied (5.2 §5.8.3 p.151 l.29-37).

### 2.6 OpenACC rules

* `copyin` of a struct does not attach its pointer members; an attach is performed by a data clause on the
  pointer's target (a pointer reference) or by an `attach` clause (3.4 §2.7.13). Child-first mapping therefore
  needs `attach`, parent-first does not.
* A parent that leaves the device while a pointer member is still attached is unspecified (3.4 §2.6.8 p.48 l.1637-1639
  and §2.6.4 p.43 l.1451-1453). The bottom-up exit order is defined, and a swapped exit order is an observation.
* Inside one directive, attach actions are scheduled after transfers in and detach before transfers out (3.4
  §2.7.2 p.52 l.1785-1786, l.1798-1799), so a single `data` construct with the struct and its members is defined.

### 2.7 Function results (hand-written programs)

The `fnres` programs are written by hand, six in all. In them a device function returns a struct (C) or derived
type (Fortran) that holds a pointer into a mapped array, a device function returns the pointer to the next object
of a chain, or a function returns a struct with a fixed-size array computed from a mapped pointer member. The called
procedures are `declare target` (5.2 §13.8 p.285 l.2-3).

## 3. The legality model

`nested_gen.validate` replays a plan against the rules above. A program is defined when the replay reaches the end
clean. It is unspecified when it touches a place the spec leaves open (listed in 2.5, 2.6, a cyclic mapper). It is
illegal when it breaks a restriction or reads storage no map made visible. The replay checks these points:

1. blocks are created by the first construct that lists them; reference counts are balanced at the end;
2. a pointer is attached iff a construct lists its target while its holder exists and either end is new
   (OpenMP), or a data clause / attach clause names it while both ends are present (OpenACC); the kernel may
   follow only attached pointers (otherwise it would dereference a host address);
3. two list items for one block in one OpenMP construct make the program illegal (p.156 l.6-7);
4. `present` on an absent item is illegal, and so is a read of a block that no map or update initialized. Blocks the
   device wrote but nothing copied back are a plan error;
5. a program that breaks the Fortran rules of 2.5 or the OpenACC exit rule of 2.6 is unspecified;
6. data races: parallel kernels are built so that each iteration touches its own elements (aliasing shapes are
   serial); `offload.engine.prerun` re-checks every program with the rules witness.

A program counts toward a compiler only if two witnesses other than that compiler accept it. A witness is evidence
that the program is legal. One is the rules (offload.engine.rules, plus the race rule). The other is a front end of
another family: AFAR's clang/flang for the CCE and NVHPC cells, and NVHPC 26.9 for the AFAR and CCE cells. A
rejection that names a missing feature is no verdict. GCC is never a witness. Programs that are not defined are
generated, run and recorded, but never counted as a defect and never gated.

## 4. Legality labels

Every program carries one label, recorded with a reason in its header and in the campaign record.

| label | meaning |
|---|---|
| defined | The replay in section 3 reaches the end clean. A failure is a candidate finding. |
| unspecified | The spec leaves the result open. Reading storage that no map initialised (indeterminate values) is unspecified. Testing `allocated()` or `associated()` on a component of an object mapped only `from` is unspecified: no rule gives the status of a device copy made without a transfer (5.2 §5.8.3 p.151 l.34-37 lets the map treat it as unallocated). |
| illegal | A restriction with a "must" is broken, or no map made storage visible. A Fortran target mapped whole after a member of it was mapped alone is illegal (5.2 §5.8.3 p.156 l.19-22: "all of the original storage must have corresponding storage"). |
| pending | Neither a defect nor a negative: the cached spec text has no rule that decides the program. Two cases follow. |

* **Mapper cycle.** A declare mapper of a self-referential type (a list or tree node whose mapper maps the child) is a cyclic definition: unspecified (5.2 §5.8.8 p.164 l.9-10). Draws made with `--current-labels` apply it; the default draw (`legacy=True`) does not.
* **OpenACC overlap.** An OpenACC alias-sub program whose strategy puts an array and the section another level points to in one clause set (`one`: one compute construct; `tdata`: one data construct) has a var that overlaps another var of the same directive. The cached OpenACC 3.4 text has no sentence on overlap, partial presence or shared storage between the vars of one directive, so the program is `pending`. The `enter` strategy puts the levels in separate directives and stays defined. The label is applied after the draw, so it does not change which programs are drawn. The sampler sees `program(cfg, review=False)`, and the constant is `G.ACC_OVERLAP_PENDING`.
* **Fortran OpenACC derived types.** A derived-type variable and its components in one data directive over a tree or an aliasing section are refused by both gfortran and ftn, and the cached OpenACC 3.4 text has no rule that makes them defined (`PENDING_WHY` in `offload/engine/nested_gen.py`).

Failures of programs that are not `defined` are observations. They are generated, run and recorded, and never counted as a defect or gated.

## 5. Sampling

`nested_gen.pilot(n, seed, neg_frac, min_cover, legacy, max_tries)` is deterministic for a given argument set.

1. It draws configurations at random with weights: chain 62%, list 8%, tree 7%, diamond 7%, alias 5%, alias-sub 4%, twin 2%; depth 1 to 4; per-level link, data and role at random; NULL links 15%; parallel kernel 40%.
2. It keeps the defined ones until each language/model quota is met (C OpenMP 42%, Fortran OpenMP 30%, C OpenACC 14%, Fortran OpenACC 14%).
3. It tops up until every axis value the language and model can express has at least `min_cover` defined programs (`coverage` reports any shortfall). `min_cover` is 4 by default.
4. It adds the unspecified draws, and mutations of defined programs as marked negatives: a dropped pointer target, a bottom-up map without re-listing, a list item named twice, a swapped OpenACC exit, an `alloc`-only read.
5. It appends the six function-result programs.

Shapes that no language and model can express are observations, not gaps. Fortran OpenMP has no legal diamond or alias plan (section 2.5).

## 6. Running it

```
python3 -I tools/campaigns/nested.py gen --n 400 --seed 1
python3 -I tools/campaigns/nested.py gen --name big --n 1000 --seed 11 --current-labels --min-cover 8 --max-tries 600
```

`gen` writes `results/nested/<name>/` (default name `main`, default `--n 400 --seed 1`) and records the parameters in `meta.json`. Without `--current-labels` the draw uses the original labels (`legacy=True`, `min_cover` 4). With it, the draw uses the current labels and `--min-cover` (default 8) and `--max-tries` (default 600).

The other subcommands are those of the generic runner (`python3 -I tools/campaign.py nested <subcommand>`; `tools/campaigns/nested.py` forwards to it):

| subcommand | purpose |
|---|---|
| `prerun`, `witness`, `legality` | the rules witness, the AFAR front-end witness, the NVHPC compile-only witness (wingtip, over ssh) and the per-family legality table |
| `run` | compile and run the cells (resumable) |
| `gate` | reproduction gate for failing cells |
| `report`, `cluster` | tables and failure clusters |
| `confirm` | confirmer on stored evidence (see [confirm.md](confirm.md)) |

`tools/campaigns/nested_findings.py` turns the gated failures into findings. [wingtip.md](wingtip.md), [toolchains.md](toolchains.md) and [regenerate.md](regenerate.md) cover the rest of the tooling.

## 7. Readings taken, and what is not covered

* The Fortran base-pointer reading of section 2.5 is the conservative one (the pointer of `p%q%r` is `p%q`). A compiler that maps both in one construct is not wrong for doing so; the program is not counted.
* `declare target` for a global root is spelled `declare target(g)`, the extended-list form of every OpenMP version, because `to(g)` is rejected by LLVM under `-fopenmp-version=52` and `enter(g)` by CCE 19/20 and NVHPC.
* Members-only maps (`map(p->x[0:n])` without the struct) are not generated: 5.2 does not say how `p` is translated when no list item names `*p`.
* Not generated: more than two children per link, depth above four, unions, bit-fields, function pointers, C++ references, classes and lambdas, `use_device_ptr`/`is_device_ptr`, named mappers, `declare variant`, more than one device, async and `nowait`, ACC `declare` and `routine`, pointer rank remapping, coarrays.
