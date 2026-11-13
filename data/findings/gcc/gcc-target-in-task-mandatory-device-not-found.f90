! # Finding (GCC 16.2): the Fortran form of gcc-c-target-in-task-mandatory-device-not-found.c
!
! - toolchains: gcc_g90 (GCC 16.2.0, AMD Instinct MI250X gfx90a, Tioga) and gcc_sm80 (GCC 16.2.0,
!   NVIDIA A100 sm_80, wingtip); separate memory only; -O2; OMP_TARGET_OFFLOAD=mandatory
! - build: gfortran -fopenmp -foffload=amdgcn-amdhsa -foffload-options=amdgcn-amdhsa=-march=gfx90a -O2 (gcc_g90);
!   -foffload=nvptx-none -foffload-options=nvptx-none=-march=sm_80 -foffload-options=nvptx-none=-latomic -O2 (gcc_sm80)
! - failure: run_error: OMP_TARGET_OFFLOAD is set to MANDATORY, but device not found
! - observed: `libgomp: OMP_TARGET_OFFLOAD is set to MANDATORY, but device not found`, exit 1, no kernel launch, in every run on
!   both GPUs (this file: gcc_sm80 5 of 5, gcc_g90 5 of 5; results/gcc/<tc>/probes-findings.jsonl). With OMP_TARGET_OFFLOAD unset
!   the same build runs the kernel on the device and prints `bad= 0` (ran_on_host=0) in 5 of 5 runs on each GPU.
! - expected: `bad= 0`, then `RESULT ran_on_host=0 check=pass`
! - rule: a target construct without a device clause uses the default device: "if no device clause is present, the behavior is as if
!   the device clause appears without a device-modifier and with a device-description that evaluates to the value of the
!   default-device-var ICV" (5.2 §13.2 p.276 l.21-23), and an explicit task has the encountering task's value of it: "When a task
!   construct, a parallel construct or a teams construct is encountered, each generated task inherits the values of the data
!   environment scoped ICVs from each generating task's ICV values" (5.2 §2.4 p.45 l.10-12). Under mandatory only an unavailable
!   device is an error: "The mandatory value specifies that the effect of any device construct or device memory routine that uses a
!   device that is unavailable or not supported by the implementation, or uses a non-conforming device number, is as if the
!   omp_invalid_device device number was used" (5.2 §21.2.8 p.610 l.28-30). The device is available: the same region in the initial
!   task runs on it (the control).
! - same-compiler controls (correct, 5 of 5 runs on each GPU): the same region in the initial task, without the task construct
!   (controls/gcc-target-in-task-control.{c,f90}). The GCC review's probes (tests/data/gcc_probes/inred_*.c,
!   results/gcc/<tc>/probes.jsonl, both GPUs) narrow it: the region fails the same way in an explicit task, in a parallel region
!   (single) and in a taskgroup with task_reduction (with in_reduction or with a plain map); in a plain taskgroup or with no
!   taskgroup it runs. The catalog's in_reduction programs fail through it: their target sits in a task_reduction taskgroup.
! - GCC 16.2 documentation (libgomp manual): OMP_TARGET_OFFLOAD "If set to 'MANDATORY', the program terminates with an error if any
!   device construct or device memory routine uses a device that is unavailable or not supported by the implementation, or uses a
!   non-conforming device number" (the same condition as 5.2 §21.2.8); the OpenMP 5.0 table lists "in_reduction clause on target
!   constructs": P, "nowait only stub". The catalog's in_reduction programs use no nowait and pass with OMP_TARGET_OFFLOAD unset on
!   both GPUs, so their failure is this finding's, not the stub's.
! - other families: AFAR and CCE 19/20 run the catalog's in_reduction programs on the device and pass (MI300A, both modes; MI250X);
!   CCE 21 fails to link them (cce21-in-reduction-taskwait-link.f90); NVHPC rejects in_reduction on target. The site's finding
!   matrix runs this file on every compiler.
! - gate and confirmer: 76 cells (38 gcc_g90, 38 gcc_sm80), each confirmed in the gate's four environments (a-d;
!   results/gcc/gate-tioga/ and gate-wingtip/ verdicts.jsonl); confirmer verdicts (results/gcc/confirm/batch.gcc_*.jsonl):
!   compiler_bug (R20-runtime-bug) 76
! - catalog programs (38): omp50-clause-in_reduction, omp50-clause-in_reduction-and, omp50-clause-in_reduction-eqv,
!   omp50-clause-in_reduction-iand, omp50-clause-in_reduction-ieor, omp50-clause-in_reduction-ior, omp50-clause-in_reduction-max,
!   omp50-clause-in_reduction-min, omp50-clause-in_reduction-minus, omp50-clause-in_reduction-neqv, omp50-clause-in_reduction-or,
!   omp50-clause-in_reduction-plus, omp50-clause-in_reduction-times, omp52-clause-in_reduction, omp52-clause-in_reduction-and,
!   omp52-clause-in_reduction-eqv, omp52-clause-in_reduction-iand, omp52-clause-in_reduction-ieor, omp52-clause-in_reduction-ior,
!   omp52-clause-in_reduction-max, omp52-clause-in_reduction-min, omp52-clause-in_reduction-minus, omp52-clause-in_reduction-neqv,
!   omp52-clause-in_reduction-or, omp52-clause-in_reduction-plus, omp52-clause-in_reduction-times, omp60-clause-in_reduction,
!   omp60-clause-in_reduction-and, omp60-clause-in_reduction-eqv, omp60-clause-in_reduction-iand, omp60-clause-in_reduction-ieor,
!   omp60-clause-in_reduction-ior, omp60-clause-in_reduction-max, omp60-clause-in_reduction-min, omp60-clause-in_reduction-neqv,
!   omp60-clause-in_reduction-or, omp60-clause-in_reduction-plus, omp60-clause-in_reduction-times
! - legality: read against the spec (the rule above); the catalog programs of the list are legal by construction
!   (offload.engine.gen,
!   c_gen and acc_gen; no compiler). GCC is a compiler under test only and never a legality witness.
program target_in_task
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n)
  integer :: i, host_flag, bad
  do i = 1, n
    a(i) = i
    b(i) = 0
  end do
  host_flag = 1
  !$omp task shared(a, b, host_flag)
    !$omp target map(to: a) map(from: b) map(tofrom: host_flag)
      host_flag = merge(1, 0, omp_is_initial_device())
      do i = 1, n
        b(i) = 2*a(i) + 1
      end do
    !$omp end target
  !$omp end task
  !$omp taskwait
  bad = count(b /= 2*[(i, i = 1, n)] + 1)
  print '(a,i0)', 'bad= ', bad
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', bad == 0)
end program target_in_task
! site:
! title: libgomp: with OMP_TARGET_OFFLOAD=mandatory, a target region in an explicit task stops with "device not found" (Fortran)
! summary: With OMP_TARGET_OFFLOAD=mandatory, a target region that GCC 16.2's libgomp meets in an explicit task stops the program
! + with "OMP_TARGET_OFFLOAD is set to MANDATORY, but device not found", although the same region in the initial task runs on the
! + GPU. The same happens in a parallel region and in a taskgroup with task_reduction, so every target construct with in_reduction
! + fails (70 catalog programs per GPU, Fortran and C). With OMP_TARGET_OFFLOAD unset the region runs on the device and gives the
! + right answer. Seen on the MI250X and the A100.
! control: gcc/controls/gcc-target-in-task-control.f90 the same region in the initial task (no task construct)
! same_as: gcc/gcc-c-target-in-task-mandatory-device-not-found
! end site
