module m_repro
    implicit none
    integer, parameter :: m = 439, n = 329, p = 329, buff = 10, layers = 3
    type integer_field
        integer, pointer, dimension(:,:,:) :: sf => null()
    end type integer_field
    type ghost_point
        integer, dimension(3) :: loc
        real(8), dimension(3) :: ip_loc
        integer, dimension(3) :: ip_grid
        real(8), dimension(2, 2, 2) :: interp_coeffs
        logical :: interp_valid
        integer :: ib_patch_id
        real(8) :: levelset
        real(8), dimension(3) :: levelset_norm
        logical :: slip
        integer, dimension(3) :: DB
        integer :: x_periodicity, y_periodicity, z_periodicity
    end type ghost_point
    type(integer_field) :: markers
    type(ghost_point), allocatable, dimension(:) :: gps
    !$omp declare target(markers, gps)
contains
    subroutine s_find_ghost_points()
        integer :: i, j, k, ii, jj, kk, count, local_idx, id
        logical :: is_gp
        count = 0
        !$omp target teams distribute parallel do collapse(3) private(i, j, k, ii, jj, kk, is_gp, local_idx, id) &
        !$omp& map(to: count) has_device_addr(gps)
        do i = 0, m
            do j = 0, n
                do k = 0, p
                    if (markers%sf(i, j, k) /= 0) then
                        is_gp = .false.
                        search: do ii = i - layers, i + layers
                            do jj = j - layers, j + layers
                                do kk = k - layers, k + layers
                                    if (markers%sf(ii, jj, kk) == 0) then
                                        is_gp = .true.; exit search
                                    end if
                                end do
                            end do
                        end do search
                        if (is_gp) then
                            !$omp atomic capture
                            count = count + 1
                            local_idx = count
                            !$omp end atomic
                            gps(local_idx)%loc(1) = i; gps(local_idx)%loc(2) = j; gps(local_idx)%loc(3) = k
                            id = markers%sf(i, j, k)
                            gps(local_idx)%ib_patch_id = id
                            gps(local_idx)%x_periodicity = 0; gps(local_idx)%y_periodicity = 0; gps(local_idx)%z_periodicity = 0
                            gps(local_idx)%slip = .false.
                            gps(local_idx)%DB(1) = 0; gps(local_idx)%DB(2) = 0; gps(local_idx)%DB(3) = 0
                        end if
                    end if
                end do
            end do
        end do
    end subroutine s_find_ghost_points
end module m_repro

program amd_atomic_capture_repro
    use omp_lib
    use m_repro
    implicit none
    integer :: tot, host_flag, spacing, nper, trials, t, q, i, j, k, a, b, c, id, num_gps, bad, dup, missing
    integer, allocatable :: hits(:, :, :)
    character(len=16) :: arg
    spacing = 10
    nper = 50
    trials = 2
    tot = 0; host_flag = 1
    !$omp target map(from: host_flag)
    host_flag = merge(1, 0, omp_is_initial_device())
    !$omp end target
    allocate (markers%sf(-buff:m + buff, -buff:n + buff, -buff:p + buff), hits(0:m, 0:n, 0:p))
    markers%sf = 0; id = 0
    do a = 0, nper - 1; do b = 0, nper - 1; do c = 0, nper - 1
        if (8 + a*spacing > m - 8 .or. 8 + b*spacing > n - 8 .or. 8 + c*spacing > p - 8) cycle
        id = id + 1
        do k = -4, 4; do j = -4, 4; do i = -4, 4
            if (i*i + j*j + k*k <= 16) markers%sf(8 + a*spacing + i, 8 + b*spacing + j, 8 + c*spacing + k) = id
        end do; end do; end do
    end do; end do; end do
    hits = 0; num_gps = 0
    do k = 0, p; do j = 0, n; do i = 0, m
        if (markers%sf(i, j, k) /= 0) then
            if (any(markers%sf(i - layers:i + layers, j - layers:j + layers, k - layers:k + layers) == 0)) num_gps = num_gps + 1
        end if
    end do; end do; end do
    allocate (gps(num_gps))
    !$omp target enter data map(always, alloc: markers%sf)
    !$omp target update to(markers%sf)
    !$omp target enter data map(alloc: gps)
    print '(A,I0,A,I0)', 'spheres ', id, '  ghost cells ', num_gps
    do t = 1, trials
        call s_find_ghost_points()
        !$omp target update from(gps)
        hits = 0; bad = 0
        do q = 1, num_gps
            if (any(gps(q)%loc < 0) .or. gps(q)%loc(1) > m .or. gps(q)%loc(2) > n .or. gps(q)%loc(3) > p) then
                bad = bad + 1; cycle
            end if
            hits(gps(q)%loc(1), gps(q)%loc(2), gps(q)%loc(3)) = hits(gps(q)%loc(1), gps(q)%loc(2), gps(q)%loc(3)) + 1
            if (markers%sf(gps(q)%loc(1), gps(q)%loc(2), gps(q)%loc(3)) /= gps(q)%ib_patch_id) bad = bad + 1
        end do
        dup = count(hits > 1); missing = num_gps - count(hits > 0)
        print '(A,I3,A,I0,A,I0,A,I0)', 'trial ', t, ': bad records ', bad, '  duplicated cells ', dup, '  missing cells ', missing
        tot = tot + bad + dup + missing
    end do
    print '(a,i0,a,a)', 'RESULT ran_on_host=', host_flag, ' check=', merge('pass', 'fail', tot == 0)
end program amd_atomic_capture_repro
