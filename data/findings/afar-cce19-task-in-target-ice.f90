program t
  implicit none
  integer :: c, r
  r = 0
  !$omp target map(from: r)
    c = 7
    !$omp task default(shared)
      c = 42
    !$omp end task
    !$omp taskwait
    r = c
  !$omp end target
  print *, 'r=', r
end program
! site:
! title: ftn/craycc: constructs documented as unsupported in offload regions (single, masked, task, ordered, scan) give internal
! + compiler errors or device link failures instead of a diagnostic
! control: ../vendor/checks/src/afar/control/afar-cce19-task-in-target-ice-control.f90 the task and taskwait constructs removed
! + (the task
! + body
! + kept)
! same_as: cce19-target-parallel-single-ice
! end site
