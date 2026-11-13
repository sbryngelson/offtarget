module m_cbc
    use m_global_parameters
    use m_compute_cbc
    type(int_bounds_info) :: is1, is2, is3  !< Indical bounds in the s1-, s2- and s3-directions
contains
    subroutine s_cbc(q_prim_vf, flux_vf, flux_src_vf, cbc_dir_norm, cbc_loc_norm, ix, iy, iz)
        real(wp)                                               :: dpres_ds
            real(wp), dimension(sys_size) :: L
            real(wp), dimension(num_fluids) :: alpha_rho, dalpha_rho_ds, mf
            real(wp), dimension(num_vels)   :: vel, dvel_ds
            real(wp), dimension(num_fluids) :: adv_local, dadv_ds
        real(wp), dimension(10) :: Ys, h_k, dYs_dt, dYs_ds, Xs, Gamma_i, Cp_i
        real(wp), dimension(3)               :: lambda
        real(wp)                             :: rho         !< Cell averaged density
        real(wp)                             :: c
!$omp target teams distribute parallel do !$omp& !$omp& !$omp& !$omp& !$omp&
                do r = is3%beg, is3%end
                            call s_compute_nonreflecting_subsonic_outflow_L(lambda, L, rho, c, mf, dalpha_rho_ds, dpres_ds, &
                                & dvel_ds, dadv_ds, dYs_ds)
                end do
!$omp end target teams distribute parallel do
    end subroutine s_cbc
end module m_cbc
