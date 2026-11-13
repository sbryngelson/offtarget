! fuzz-5 oop sample, AFAR failures reduced by hand: control of C_int_modi_alloc
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 48
! observed HSA_XNACK=1: r1= 48
! observed HSA_XNACK=0: r1= 48
! legality: offload.engine.rules accept
program p
  implicit none
  integer, parameter :: n = 16, m = 3
  integer :: ia(n), i, j
  integer :: r1
  integer, allocatable :: o1(:, :)
  do i = 1, n
    ia(i) = mod(i * 7, 11)
  end do
  allocate(o1(n, m))
  o1 = 0
  r1 = 0
  !$omp target map(tofrom: r1)
  !$omp teams
  !$omp distribute
  do i = n, 1, -1
    !$omp parallel
      !$omp do
      do j = 1, m
        o1(i, j) = 0
        !$omp atomic
        r1 = r1 + 1
      end do
      !$omp end do
    !$omp end parallel
  end do
  !$omp end distribute
  !$omp end teams
  !$omp end target
  print '(a,i0)', 'r1= ', int(r1)
end program p
