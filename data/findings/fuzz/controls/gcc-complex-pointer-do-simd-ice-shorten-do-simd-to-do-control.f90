! Control of gcc-complex-pointer-do-simd-ice.f90: shorten do simd to do at line 14; one change from the reduction; passes on gcc/0.
! Every step passed the legality rules witness (offload.engine.prerun rules); the front-end witness (offload.engine.prerun.check) is
!   still to run on Tuolumne.
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer, parameter :: n = 3, m = 2
  complex(4), pointer :: o1(:, :)
  complex(4), target :: o1t(n, m)
  integer :: i, j, hf
  o1 => o1t
  o1 = 0
  hf = 1
  !$omp target map(tofrom: hf)
    hf = merge(1, 0, omp_is_initial_device())
    do i = 1, n
      !$omp do
      do j = 1, m
        o1(i, j) = i
      end do
    end do
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', merge('pass', 'fail', all(o1(:, 1) == &
      & [(cmplx(i), i = 1, n)]))
end program p
