! Fortran slice directives copied verbatim from corpus/omp_examples
! (OpenMP Examples). Each block is preceded by its source file:line.
! omp_examples/devices/sources/target.4.f90:12
   !$omp target map(to: v1(1:N), v2(:N)) map(from: p(1:N))
! omp_examples/devices/sources/target_data.1.f90:10
   !$omp target data map(to: v1, v2) map(from: p)
! omp_examples/devices/sources/target_update.3.f90:32
       !$omp target update to(mapper(custom) : s)
! omp_examples/devices/sources/target_unstructured_data.1.f90:14
      !$omp target enter data map(alloc:A)
! omp_examples/devices/sources/target_unstructured_data.1.f90:20
      !$omp target exit data map(delete:A)
! omp_examples/devices/sources/declare_target.6.f90:8
   !$omp declare target link(sp,sv1,sv2)
! omp_examples/devices/sources/declare_target.4.f90:7
!$omp declare target (N,Q)
! omp_examples/data_environment/sources/target_task_reduction.1.f90:9
      !$omp declare target enter(device_compute)
! omp_examples/devices/sources/usm_scalar_ptr_ref_asc.1.f90:7
   !$omp requires unified_shared_memory
! omp_examples/devices/sources/async_target.3.f90:17
      !$omp target teams distribute parallel do nowait &
      !$omp&                    map(to: v1(1:n/2))   &
      !$omp&                    map(to: v2(1:n/2))   & 
      !$omp&                    map(from: vxv(1:n/2)) 
! omp_examples/devices/sources/target.6.f90:17
   !$omp target parallel do  &
   !$omp&   if(target: N>THRESHHOLD1) if(parallel: N>THRESHOLD2) &
   !$omp&   map(to: v1, v2 ) map(from: p)
! omp_examples/devices/sources/teams.4.f90:17
   !$omp distribute parallel do reduction(+:sum) &
   !$omp&  dist_schedule(static, 1024) schedule(static, 64)
! omp_examples/devices/sources/teams.3.f90:10
   !$omp target teams map(to: B, C)  &
   !$omp&             defaultmap(tofrom:scalar) reduction(+:sum)
! omp_examples/devices/sources/teams.2.f90:12
    !$omp teams num_teams(num_teams) thread_limit(block_threads) &
    !$omp&  reduction(+:sum)
! omp_examples/data_environment/sources/scan.3.f90:19
   !$omp parallel do simd reduction(inscan,+: x) private(tmp)
! omp_examples/devices/sources/target_fort_allocatable_map.1.f90:32
    !$omp target map(always,tofrom:c) ! Target 3 
! omp_examples/devices/sources/device.6.f90:44
   !$omp target has_device_addr(d_buf) depend(depobj: obj)
! omp_examples/devices/sources/self_map.2.f90:48
   !$omp target teams loop defaultmap(self: aggregate)
! omp_examples/devices/sources/target_teams_workdistribute.3.f90:17
        !$omp target teams workdistribute map(to:bb,cc) &
        !$omp        map(from:aa,dd,f,ee)
! omp_examples/devices/sources/target_data.7.f90:15
      !$omp target if(N>THRESHOLD) map(to: v1, v2)
