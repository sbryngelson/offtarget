program bind_thread_repro
  use omp_lib
  implicit none
  integer, parameter :: n = 64
  integer :: hit(n, 1024), nthr, tid, i, k, short
  hit = 0
  nthr = -1
  !$omp target map(tofrom: hit, nthr)
    !$omp parallel private(tid)
      tid = omp_get_thread_num()
      if (tid == 0) nthr = omp_get_num_threads()
        do i = 1, n
          if (tid < 1024) hit(i, tid + 1) = hit(i, tid + 1) + 1
        end do
    !$omp end parallel
  !$omp end target
  short = 0
  do k = 1, min(nthr, 1024)
    if (sum(hit(:, k)) /= n) short = short + 1
  end do
  print '(a,i0,a,4(1x,i0))', 'threads=', nthr, ' iterations run by threads 0-3:', &
    (sum(hit(:, k)), k = 1, 4)
  print '(a,i0,a)', 'threads that did not run all 64 iterations: ', short, ' (expected 0)'
end program bind_thread_repro
