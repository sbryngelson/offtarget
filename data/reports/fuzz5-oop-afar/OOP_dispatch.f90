! fuzz-5 oop sample, AFAR failures reduced by hand: oop negative: dispatch through CLASS(ob_t) of a device-local object in target teams distribute parallel do
! build: amdflang -fopenmp --offload-arch=gfx942 -O2 (AFAR 24.3.0, MI300A)
! run: OMP_TARGET_OFFLOAD=mandatory HSA_XNACK=1 and HSA_XNACK=0 ./a.out
! expected (the host run, OMP_TARGET_OFFLOAD=disabled): r1= 1077751575
! observed HSA_XNACK=1: r1= 1077751575
! observed HSA_XNACK=0: r1= 1077751575
! legality: offload.engine.rules accept; no second front end (CCE cannot link device dispatch, NVHPC rejects type-bound calls on the device)
module m
  implicit none
  type :: ob_t
    integer :: k = 0
  contains
    procedure :: f => ob_f
    procedure :: g => ob_g
  end type ob_t
  type, extends(ob_t) :: ox_t
    integer :: j = 0
  contains
    procedure :: f => ox_f
  end type ox_t
contains
  integer function ob_f(s, x)
    !$omp declare target
    class(ob_t), intent(in) :: s
    integer, intent(in) :: x
    ob_f = mod(x * 4 + s%k, 1009)
  end function ob_f
  integer function ob_g(s, x)
    !$omp declare target
    class(ob_t), intent(in) :: s
    integer, intent(in) :: x
    ob_g = s%f(x) + s%k
  end function ob_g
  integer function ox_f(s, x)
    !$omp declare target
    class(ox_t), intent(in) :: s
    integer, intent(in) :: x
    ox_f = mod(s%ob_t%f(x) + s%j * 5, 89)
  end function ox_f
  integer function od(s, x)
    !$omp declare target
    class(ob_t), intent(in) :: s
    integer, intent(in) :: x
    od = s%f(x)
  end function od
  integer function oo1(x)
    !$omp declare target
    integer, intent(in) :: x
    type(ob_t) :: o
    o%k = 41
    oo1 = od(o, x)
  end function oo1
  integer function oo2(x)
    !$omp declare target
    integer, intent(in) :: x
    type(ox_t) :: o
    o%k = 41
    o%j = 7
    oo2 = od(o, x)
  end function oo2
end module m
program t
  use m
  implicit none
  integer, parameter :: n = 64
  integer :: o(n), i
  integer(8) :: cs
  o = 0
  !$omp target teams distribute parallel do map(from: o)
  do i = 1, n
    o(i) = oo1(i)
  end do
  cs = 0
  do i = 1, n
    cs = cs * 31 + o(i)
    cs = mod(cs, 2147483629_8)
  end do
  print '(a,i0)', 'r1= ', cs
end program t
