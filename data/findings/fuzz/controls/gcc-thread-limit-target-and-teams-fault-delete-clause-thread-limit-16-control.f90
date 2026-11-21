! Control of gcc-thread-limit-target-and-teams-fault.f90: delete clause thread_limit(16) at line 7; one change from the reduction;
!   passes on gcc/0.
! Every step passed the legality rules witness (offload.engine.prerun rules); the front-end witness (offload.engine.prerun.check) is
!   still to run on Tuolumne.
program p
  use omp_lib, only: omp_is_initial_device
  implicit none
  integer :: i, j, hf
  hf = 1
  !$omp target thread_limit(1) map(tofrom: hf)
    !$omp teams distribute
    do i = 1, 16
      if (i == 1) hf = merge(1, 0, omp_is_initial_device())
      !$omp parallel
      do j = 8, 1, -1
      end do
      !$omp end parallel
    end do
  !$omp end target
  print '(a,i0,a,a)', 'RESULT ran_on_host=', hf, ' check=', 'pass'
end program p
