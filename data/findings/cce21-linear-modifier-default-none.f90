! Finding: CCE 21 rejects the OpenMP 5.2 linear modifier syntax
! under default(none) with a false data-sharing diagnostic.
!
! Legal OpenMP 5.2: linear(x: val, step(1)) on a worksharing-loop (5.2
! §5.4.6 pp.117-120; val is the default for a non-reference variable).
! linear is a data-sharing attribute clause, so x has an explicitly
! determined data-sharing attribute and default(none) is satisfied (5.2
! §5.4.1 p.109). At the start of iteration i, x = 3 + (i - 1); after the
! loop x = n + 3, reading "The value corresponding to the sequentially last
! logical iteration of the associated loops is assigned to the original list
! item" (5.2 §5.4.6 p.118) as the list item's value at the end of that
! iteration, as for lastprivate (the other reading, its value at the start,
! gives n + 2; CCE 21's failure is a compile-time rejection either way).
! Expected: "RESULT ran_on_host=0 check=pass".
! Legality rests on the quoted spec text: cited gfortran 13.3.1
! -fopenmp as an independent witness; gfortran/gcc -fopenmp are withdrawn
! as offload legality witnesses (data/reports/rulings.md).
!
! Observed (tuolumne, MI300A, both memory modes, -O2, 2026-10-22,
! data/evidence/triage_probe/linear_mod.f90 and linear_mod_nodn.f90,
! results/t27b/probes.jsonl):
! - CCE 21.0.3 (whose intro_openmp(7) lists "new linear clause syntax
!   (Fortran only)" among its OpenMP 5.2 features): ftn-1510 "Variable "X"
!   must have its data scope explicitly declared because DEFAULT(NONE) was
!   specified". Without default(none) shared(a, b): internal compiler error
!   "ACC - barrier/reset/protected last private not supported" (the class of
!   fuzz/1391-cce20.f90).
! - CCE 19.0.0, 20.0.2: ftn-113, VAL read as an undeclared variable (they do
!   not claim the 5.2 syntax).
! - AFAR amdflang 24.0.0git: crashes (ICE) in both forms.
! The catalog's omp52/60-clause-linear-val programs are rejected on every
! compiler because of these.
!
! ftn -fopenmp -O2
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 64
  integer :: a(n), b(n), i, x, host_flag
  a = [(i, i = 1, n)]
  b = 0
  x = 3
  host_flag = 1
  !$omp target map(to: a) map(from: b) map(tofrom: x, host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    !$omp parallel do default(none) shared(a, b) linear(x: val, step(1))
    do i = 1, n
      b(i) = 2*a(i) + 1 + (x - (i + 2))
      x = x + 1
    end do
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', &
    merge('pass', 'fail', all(b == 2*a + 1) .and. x == n + 3)
end program p
! site:
! title: ftn: internal compiler error "ACC - barrier/reset/protected last private not supported" for linear and lastprivate on a
! + loop in a target region
! same_as: catalog/cce-linear-lastprivate-ice
! end site
