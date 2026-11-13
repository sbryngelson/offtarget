! Finding: defaultmap(none) on a target construct whose every
! referenced variable has a data-environment attribute is rejected by every
! compiler.
!
! Legal OpenMP 5.2: "If implicit-behavior is none, each variable that is
! specified by variable-category and is referenced in the construct but does
! not have a predetermined data-sharing and does not appear in an enter or
! link clause on a declare target directive must be explicitly listed in a
! data-environment attribute clause on the construct" (5.2 §5.8.7 p.162).
! a, b and host_flag are mapped; n is a named constant, not a variable; i is
! listed in private(i), a data-environment attribute clause (whether it is
! also predetermined private as a loop iteration variable, 5.2 §5.1.1 p.97,
! depends on reading target as a task generating construct; the finding
! does not rest on it). Expected: "RESULT ran_on_host=0 check=pass".
!
! Legality rests on the quoted spec text only (registry
! RUL-LEGAL-DEFAULTMAP-NONE): there is no independent compiler witness.
! Cited gfortran 13.3.1 -fopenmp as one; the maintainer withdrew
! gfortran/gcc -fopenmp as offload legality witnesses on 2026-10-23 (final
! review 3, data/reports/rulings.md), so the catalog cells are
! unsupported_everywhere (every family rejects), not compiler_bug (R12a
! cannot fire without a witness). The variant without private(i)
! (data/evidence/triage_probe/dmap_none_noi.f90) is contested.
! (2026-10-24): NVHPC 25.11 and 26.9 (wingtip, the configured
! witness) accept the omp50/52/60-clause-defaultmap-none programs, but
! that is no witness either (ruling R2): nvc also
! compiles and runs the illegal C defaultmap(none) variants
! (omp52/60-c-illegal-defaultmap-map-003, a referenced variable not
! listed), and nvfortran compiles a Fortran target defaultmap(none) that
! references unlisted x and n; NVHPC does not enforce defaultmap(none), so
! its accept says nothing about legality (offload.engine.confirm.witness
! uncalibrated; catalog/legality_witness.yaml calibration rows). The cells
! stay unsupported_everywhere.
!
! Observed (tuolumne, MI300A, both memory modes, -O2, 2026-10-22,
! data/evidence/triage_probe/dmap_none.f90 and dmap_none_noi.f90 (without private(i)),
! results/t27b/probes.jsonl): every compiler under test rejects this form
! (and the variant without private(i)):
! - AFAR amdflang 24.0.0git: "The DEFAULTMAP(NONE) clause requires that 'i'
!   must be listed in a data-sharing attribute, data-mapping attribute, or
!   is_device_ptr clause";
! - CCE 20.0.2, 21.0.3: ftn-1964 "Variable "I" must have its data mapping
!   attribute explicitly declared because default map(none) was specified";
! - CCE 19.0.0: ftn-1964 "Variable "B" ..." although b is in map(from: b).
! The catalog's omp50/52/60-clause-defaultmap-none programs are rejected on
! every compiler because of it.
!
! amdflang -fopenmp --offload-arch=gfx942 -O2; ftn -fopenmp -O2
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), i, host_flag
  a = [(i, i = 1, n)]
  b = 0
  host_flag = 1
  !$omp target map(to: a) map(from: b) map(tofrom: host_flag) defaultmap(none) private(i)
    host_flag = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      b(i) = 2*a(i) + 1
    end do
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', &
    merge('pass', 'fail', all(b == 2*a + 1))
end program p
! site:
! title: ftn: defaultmap(none) rejected although every referenced variable has a data-environment attribute (ftn-1964)
! control: ../vendor/checks/src/other/control/defaultmap-none-loop-variable-control.f90 defaultmap(none) removed
! end site
