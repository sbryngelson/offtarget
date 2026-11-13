module fuzz_mod
  implicit none
contains
end module fuzz_mod
program fuzz_prog
  implicit none
  integer, parameter :: n = 32, m = 2
  type :: rec_t
    integer :: a(n)
    integer, allocatable :: q(:)
  end type rec_t
  type(rec_t) :: dr
  integer, allocatable :: ib(:)
  integer, allocatable :: o1(:, :)
  integer, pointer :: o2(:, :)
  integer :: s3(n)
  integer, allocatable :: s4(:)
  integer, target :: o2t(n, m)
  integer, target :: tgc(n)
  integer :: i, j
  integer(8) :: cs
  allocate(ib(n))
  allocate(o1(n, m))
  allocate(s4(n))
  allocate(dr%q(n))
  o2 => o2t
  do i = 1, n
    ib(i) = mod(i * 16 + 35, 30011) - 1727
  end do
  do i = 1, n
    dr%a(i) = mod(i * 5 + 17, 211) - 48
    dr%q(i) = mod(i * 50 + 39, 1009) - 500
    tgc(i) = mod(i * 55 + 22, 97) - 32
  end do
  o1 = 0
  o2 = 0
  s3 = 0
  s4 = 0
  !$omp target map(to: dr%a, ib)
    !$omp teams
      !$omp distribute
      do i = n, 1, -1
        !$omp parallel firstprivate(i)
          !$omp do
          do j = 1, m
            o1(i, j) = mod(mod(i, 13), 1009)
          end do
        !$omp end parallel
      end do
    !$omp end teams
  !$omp end target
  cs = 0
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o1(i, j), 8), 2147483629_8)
    end do
  end do
  do j = 1, m
    do i = 1, n
      cs = modulo(cs * 31_8 + int(o2t(i, j), 8), 2147483629_8)
    end do
  end do
  print '(a,i0)', 'RESULT checksum=', cs
end program fuzz_prog
