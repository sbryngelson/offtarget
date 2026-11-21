! Control of gcc-target-repeated-parallel-num-threads-abort.f90: delete clause num_threads(2) at line 9; one change from the
!   reduction; passes on gcc/0.
! Every step passed the legality rules witness (offload.engine.prerun rules); the front-end witness (offload.engine.prerun.check) is
!   still to run on Tuolumne.
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: i, j, hf
  hf = 1
  !$omp target map(tofrom: hf)
    hf = merge(1, 0, omp_is_initial_device())
    do i = 50, 1, -1
      !$omp parallel
        do j = 1, 2
        end do
      !$omp end parallel
    end do
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', 'pass'
end program p
