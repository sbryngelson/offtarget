program fuzz_prog
  use omp_lib, only: omp_is_initial_device
  use fuzz_dmod
  use fuzz_dfun, only: gd1
  use fuzz_amod, only: ga1
  use fuzz_smod, only: gs1
  implicit none
  interface
    integer function ge1(x)
      !$omp declare target
      integer, intent(in) :: x
    end function ge1
  end interface
  integer, parameter :: n = 48, m = 3
  type :: nd_t
    integer :: k(n)
    integer :: o1(n)
  end type nd_t
  type :: rec_t
    integer :: a(n)
    integer :: s
    type(nd_t) :: nd
  end type rec_t
  type(rec_t) :: dr
  integer, target :: ia(n)
  integer, allocatable :: ib(:)
  integer, target :: ic(n, m)
  integer, allocatable :: as1
  real(4) :: xr4(n)
  double precision :: xr8(n)
  complex(kind=4), allocatable :: xz4(:)
  logical :: xl(n)
  character(len=4), allocatable :: xc(:)
  integer(kind=2) :: xk2(n)
  character(len=8) :: xs
  integer :: i, j, jj, p1, hf2
  integer(8) :: cs
  allocate(ib(n))
  allocate(xz4(n))
  allocate(xc(n))
  allocate(as1)
  do i = 1, n
    ia(i) = mod(i * 20 + 37, 211) - 74
  end do
  do i = 1, n
    ib(i) = mod(i * 19 + 13, 1009) - 462
  end do
  do j = 1, m
    do i = 1, n
      ic(i, j) = mod((i + 3 * j) * 32 + 39, 30011) - 1506
    end do
  end do
  do i = 1, n
    xr4(i) = real(mod(i * 9 + 41, 1009) - 363, 4) * 0.5
    xr8(i) = real(mod(i * 46 + 12, 211) - 94, 8) * 0.5d0
    xz4(i) = cmplx(mod(i * 47 + 46, 101) - 19, mod(i * 46, 17) - 8, 4)
    xl(i) = mod(i * 6 + 37, 3) == 0
    xc(i) = achar(65 + mod(i * 37, 26)) // achar(97 + mod(i + 28, 26)) // achar(48 + mod(i, 10)) // &
        & '#'
    xk2(i) = int(mod(i * 44 + 46, 16001) - 8000, 2)
    dr%a(i) = mod(i * 58 + 6, 211) - 70
    dr%nd%k(i) = mod(i * 39 + 12, 211) - 24
    gtab(i) = mod(i * 61 + 8, 211) - 15
    gs%k(i) = mod(i * 24 + 46, 211) - 100
  end do
  xs = 'zyVjJmrn'
  dr%s = 38
  as1 = 58
  dr%nd%o1 = 0
  go2 = 0
  p1 = 6
  hf2 = 0
  !$omp target update to(gtab, go2, gs)
  ! fuzz: kernels
  call kp1(ic, dr)
  !$omp target parallel map(to: ic(:, :)) map(tofrom: hf2) defaultmap(firstprivate) &
  !$omp& thread_limit(8) num_threads(4)
    !$omp single
      hf2 = merge(1, 0, omp_is_initial_device())
      do i = 1, n
        go2(i) = mod((i + ishft(iand(ishft(iand(ic(i, (mod(((i * 4) + 8), m) + 1)), 1023), (-4)), 1023), &
            & 1)), 1009)
      end do
    !$omp end single
  !$omp end target parallel
  !$omp target update from(go2)
  ! fuzz: checksum
  cs = 0
  do i = 1, n
    cs = modulo(cs * 31_8 + int(dr%nd%o1(i), 8), 2147483629_8)
  end do
  do i = 1, n
    cs = modulo(cs * 31_8 + int(go2(i), 8), 2147483629_8)
  end do
  print '(a,i0,a,i0)', 'RESULT checksum=', cs, ' ran_on_host=', max(hf2, 0)
contains
  subroutine kp1(ic, dr)
    integer, intent(inout) :: ic(:, :)
    type(rec_t), intent(inout) :: dr
    integer :: i, j, jj
    !$omp target parallel loop map(tofrom: dr%nd%o1) map(tofrom: ic) thread_limit(32) &
    !$omp& shared(dr, ic)
    do i = 1, n
      dr%nd%o1(i) = iand(mod(ic(i, (mod(((i * 6) + 7), m) + 1)), 7), 255)
    end do
  end subroutine kp1
end program fuzz_prog
