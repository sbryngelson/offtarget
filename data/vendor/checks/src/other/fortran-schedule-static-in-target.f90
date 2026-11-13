program sched_repro
  use omp_lib
  implicit none
  integer, parameter :: m = 1000
  integer :: tid(m), tid2(m), nthr, i, bad, bad2
  tid = -1
  tid2 = -1
  nthr = -1
  !$omp target map(from: tid, tid2, nthr)
    !$omp parallel do schedule(static, 4)
      do i = 1, m
        if (i == 1) nthr = omp_get_num_threads()
        tid(i) = omp_get_thread_num()
      end do
    !$omp end parallel do
    !$omp parallel do schedule(static)
      do i = 1, m
        tid2(i) = omp_get_thread_num()
      end do
    !$omp end parallel do
  !$omp end target
  bad = 0
  do i = 1, m
    if (tid(i) /= mod((i - 1)/4, nthr)) bad = bad + 1
  end do
  bad2 = 0
  do i = 2, m
    if (tid2(i) /= tid2(i - 1) .and. any(tid2(1:i - 1) == tid2(i))) bad2 = bad2 + 1
  end do
  print '(a,i0,a,12(1x,i0))', 'threads=', nthr, ' static,4 tid(1:12)=', tid(1:12)
  print '(a,12(1x,i0))', 'static tid(1:12)=', tid2(1:12)
  print '(a,i0,a,i0,a)', 'static,4 iterations on the wrong thread: ', bad, ' of ', m, ' (expected 0)'
  print '(a,i0,a)', 'static: iterations starting a second chunk of a thread: ', bad2, ' (expected 0)'
end program sched_repro
