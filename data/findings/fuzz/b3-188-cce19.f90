! Minimized by compliance.fuzz_min from fuzz seed 188 (fuzz-3).
! toolchain: cce19 (-O2, HSA_XNACK=1, OMP_TARGET_OFFLOAD=mandatory)
! failure: ice (ice: INTERNAL COMPILER ERROR: "Unexpected schedule" (v_mt_translate.c, line 4112, version <v>))
! expected: compiles
! observed: internal compiler error: ice: INTERNAL COMPILER ERROR:  "Unexpected schedule"
!   (/workspace/crayftn/pdgcs/v_mt_translate.c, line 4112, version cc4d36e4ff3377d45f0e6e892b5dacd82009a0ca)
! Legal OpenMP 5.2: offload.engine.prerun.check accepts it (rerun: offload.engine.rules with the
!   race rule and the restriction checks, and the AFAR flang front end, not under test here); no
!   compiler under test, gfortran or gcc is a legality witness.
! also fails on: cce20, cce21
program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 48, m = 4
  integer, allocatable :: ia(:)
  integer, allocatable :: ib(:)
  integer, allocatable :: ic(:, :)
  integer, allocatable :: as1
  integer, pointer :: o1(:, :)
  integer, target :: o1t(n, m)
  integer :: i, j, jj, p1, p2, r1a, lp1, hf1
  integer(8) :: cs
  allocate(ia(n))
  allocate(ib(n))
  allocate(ic(n, m))
  allocate(as1)
  o1 => o1t
  do i = 1, n
    ia(i) = mod(i * 42 + 2, 1009) - 210
  end do
  do i = 1, n
    ib(i) = mod(i * 5 + 50, 1009) - 327
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 1 * j) * 42 + 27, 211) - 23
    end do
  end do
  as1 = 25
  o1 = 0
  p1 = 8
  p2 = -7
  r1a = 76
  lp1 = 0
  hf1 = 0
  ! fuzz: kernels
  ! fuzz: checksum
  cs = 0
  cs = modulo(cs * 31_8 + int(r1a, 8), 2147483629_8)
  cs = modulo(cs * 31_8 + int(lp1, 8), 2147483629_8)
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1t(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf1, 0)
contains
  subroutine kp1(as1, ia, ib, ic, o1, p1)
    integer, allocatable, intent(inout) :: as1
    integer, allocatable, intent(inout) :: ia(:)
    integer, intent(inout) :: ib(n)
    integer, allocatable, intent(inout) :: ic(:, :)
    integer, intent(inout) :: o1(:, :)
    integer, intent(in), optional :: p1
    integer :: i, j, jj
    !$omp target teams
      !$omp distribute parallel do schedule(dynamic) dist_schedule(static, 16)
      do i = 1, n
      end do
    !$omp end target teams
  end subroutine kp1
end program fuzz_prog
! site:
! title: ftn: internal compiler error "Unexpected schedule" for distribute parallel do schedule(dynamic) dist_schedule(static, 16)
! control: ../vendor/checks/src/fuzz/control/fuzz-b3-188-cce19-control.f90 schedule(dynamic) removed from the distribute parallel do
! end site
! spec (requirement): in a composite construct each clause that is permitted on only one leaf construct applies to that leaf:
!   schedule applies to the worksharing loop and dist_schedule to distribute, and a dynamic schedule gives each thread a chunk
!   until none remain.
! "Some clauses are permitted only on a single leaf construct of the combined or composite construct, in which case the effect
!   is as if the clause is applied to that specific construct." (5.2 §17.2 p.339 l.31-33)
! "If the kind argument is dynamic, each thread executes a chunk, then requests another chunk, until no chunks remain to be
!   assigned. Each chunk contains chunk_size iterations, except for the chunk that contains the sequentially last iteration, which
!   may have fewer iterations. If chunk_size is not specified, it defaults to 1." (5.2 §11.5.3 p.252 l.23-26)
! "The dist_schedule clause specifies how iterations of associated loops of a distribute construct are divided into contiguous
!   non-empty subsets, called chunks, and how these chunks are distributed among the teams of the league. if chunk_size is not
!   specified, the iteration space is divided into chunks that are approximately equal in size, and at most one chunk is
!   distributed to each initial team of the league." (5.2 §11.6.1 p.256 l.13-17)
! spec (this program): distribute parallel do schedule(dynamic) dist_schedule(static, 16) is a legal combination; CCE 19, 20 and
!   21 stop with an internal compiler error (Unexpected schedule), and compile it when schedule(dynamic) is removed.
