module {
  func.func @_QMm_reproPs_find_ghost_points() {
    omp.target kernel_type(spmd) has_device_addr(%39 -> %arg0 : !fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>) map_entries(%40 -> %arg1, %41 -> %arg2, %42 -> %arg3, %43 -> %arg4, %44 -> %arg5, %45 -> %arg6, %46 -> %arg7, %47 -> %arg8, %48 -> %arg9, %49 -> %arg10, %50 -> %arg11 : !fir.ref<i32>, !fir.ref<i32>, !fir.ref<i32>, !fir.ref<i32>, !fir.ref<i32>, !fir.ref<i32>, !fir.ref<i32>, !fir.ref<!fir.logical<4>>, !fir.ref<i32>, !fir.ref<i32>, !fir.ref<!fir.type<_QMm_reproTinteger_field{sf:!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>}>>) {
      %51:2 = hlfir.declare %arg0 {fortran_attrs = #fir.var_attrs<allocatable>, uniq_name = "_QMm_reproEgps"} : (!fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>) -> (!fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>, !fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>)
      %52:2 = hlfir.declare %arg1 {uniq_name = "_QMm_reproFs_find_ghost_pointsEcount"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
      %53:2 = hlfir.declare %arg2 {uniq_name = "_QMm_reproFs_find_ghost_pointsEi"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
      %54:2 = hlfir.declare %arg3 {uniq_name = "_QMm_reproFs_find_ghost_pointsEj"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
      %55:2 = hlfir.declare %arg4 {uniq_name = "_QMm_reproFs_find_ghost_pointsEk"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
      %56:2 = hlfir.declare %arg5 {uniq_name = "_QMm_reproFs_find_ghost_pointsEii"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
      %57:2 = hlfir.declare %arg6 {uniq_name = "_QMm_reproFs_find_ghost_pointsEjj"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
      %58:2 = hlfir.declare %arg7 {uniq_name = "_QMm_reproFs_find_ghost_pointsEkk"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
      %59:2 = hlfir.declare %arg8 {uniq_name = "_QMm_reproFs_find_ghost_pointsEis_gp"} : (!fir.ref<!fir.logical<4>>) -> (!fir.ref<!fir.logical<4>>, !fir.ref<!fir.logical<4>>)
      %60:2 = hlfir.declare %arg9 {uniq_name = "_QMm_reproFs_find_ghost_pointsElocal_idx"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
      %61:2 = hlfir.declare %arg10 {uniq_name = "_QMm_reproFs_find_ghost_pointsEid"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
      %62:2 = hlfir.declare %arg11 {uniq_name = "_QMm_reproEmarkers"} : (!fir.ref<!fir.type<_QMm_reproTinteger_field{sf:!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>}>>) -> (!fir.ref<!fir.type<_QMm_reproTinteger_field{sf:!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>}>>, !fir.ref<!fir.type<_QMm_reproTinteger_field{sf:!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>}>>)
      omp.teams {
        omp.parallel private(@_QMm_reproFs_find_ghost_pointsEi_private_i32 %53#0 -> %arg12, @_QMm_reproFs_find_ghost_pointsEj_private_i32 %54#0 -> %arg13, @_QMm_reproFs_find_ghost_pointsEk_private_i32 %55#0 -> %arg14, @_QMm_reproFs_find_ghost_pointsEii_private_i32 %56#0 -> %arg15, @_QMm_reproFs_find_ghost_pointsEjj_private_i32 %57#0 -> %arg16, @_QMm_reproFs_find_ghost_pointsEkk_private_i32 %58#0 -> %arg17, @_QMm_reproFs_find_ghost_pointsEis_gp_private_l32 %59#0 -> %arg18, @_QMm_reproFs_find_ghost_pointsElocal_idx_private_i32 %60#0 -> %arg19, @_QMm_reproFs_find_ghost_pointsEid_private_i32 %61#0 -> %arg20 : !fir.ref<i32>, !fir.ref<i32>, !fir.ref<i32>, !fir.ref<i32>, !fir.ref<i32>, !fir.ref<i32>, !fir.ref<!fir.logical<4>>, !fir.ref<i32>, !fir.ref<i32>) {
          %63 = fir.alloca i32 {pinned}
          %64 = fir.alloca i32 {pinned}
          %65 = fir.alloca i32 {pinned}
          %66:2 = hlfir.declare %arg12 {uniq_name = "_QMm_reproFs_find_ghost_pointsEi"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
          %67:2 = hlfir.declare %arg13 {uniq_name = "_QMm_reproFs_find_ghost_pointsEj"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
          %68:2 = hlfir.declare %arg14 {uniq_name = "_QMm_reproFs_find_ghost_pointsEk"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
          %69:2 = hlfir.declare %arg15 {uniq_name = "_QMm_reproFs_find_ghost_pointsEii"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
          %70:2 = hlfir.declare %arg16 {uniq_name = "_QMm_reproFs_find_ghost_pointsEjj"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
          %71:2 = hlfir.declare %arg17 {uniq_name = "_QMm_reproFs_find_ghost_pointsEkk"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
          %72:2 = hlfir.declare %arg18 {uniq_name = "_QMm_reproFs_find_ghost_pointsEis_gp"} : (!fir.ref<!fir.logical<4>>) -> (!fir.ref<!fir.logical<4>>, !fir.ref<!fir.logical<4>>)
          %73:2 = hlfir.declare %arg19 {uniq_name = "_QMm_reproFs_find_ghost_pointsElocal_idx"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
          %74:2 = hlfir.declare %arg20 {uniq_name = "_QMm_reproFs_find_ghost_pointsEid"} : (!fir.ref<i32>) -> (!fir.ref<i32>, !fir.ref<i32>)
          %c0_i32_2 = arith.constant 0 : i32
          %c439_i32 = arith.constant 439 : i32
          %c1_i32 = arith.constant 1 : i32
          %c0_i32_3 = arith.constant 0 : i32
          %c329_i32 = arith.constant 329 : i32
          %c1_i32_4 = arith.constant 1 : i32
          %c0_i32_5 = arith.constant 0 : i32
          %c329_i32_6 = arith.constant 329 : i32
          %c1_i32_7 = arith.constant 1 : i32
          omp.distribute {
            omp.wsloop {
              omp.loop_nest (%arg21, %arg22, %arg23) : i32 = (%c0_i32_2, %c0_i32_3, %c0_i32_5) to (%c439_i32, %c329_i32, %c329_i32_6) inclusive step (%c1_i32, %c1_i32_4, %c1_i32_7) collapse(3) {
                hlfir.assign %arg21 to %66#0 : i32, !fir.ref<i32>
                hlfir.assign %arg22 to %67#0 : i32, !fir.ref<i32>
                hlfir.assign %arg23 to %68#0 : i32, !fir.ref<i32>
                %75 = hlfir.designate %62#0{"sf"}   {fortran_attrs = #fir.var_attrs<pointer>} : (!fir.ref<!fir.type<_QMm_reproTinteger_field{sf:!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>}>>) -> !fir.ref<!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>>
                %76 = fir.load %75 : !fir.ref<!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>>
                %77 = fir.load %66#0 : !fir.ref<i32>
                %78 = fir.convert %77 : (i32) -> i64
                %79 = fir.load %67#0 : !fir.ref<i32>
                %80 = fir.convert %79 : (i32) -> i64
                %81 = fir.load %68#0 : !fir.ref<i32>
                %82 = fir.convert %81 : (i32) -> i64
                %83 = hlfir.designate %76 (%78, %80, %82)  : (!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>, i64, i64, i64) -> !fir.ref<i32>
                %84 = fir.load %83 : !fir.ref<i32>
                %c0_i32_8 = arith.constant 0 : i32
                %85 = arith.cmpi ne, %84, %c0_i32_8 : i32
                fir.if %85 {
                  %false = arith.constant false
                  %86 = fir.convert %false : (i1) -> !fir.logical<4>
                  hlfir.assign %86 to %72#0 : !fir.logical<4>, !fir.ref<!fir.logical<4>>
                  scf.execute_region no_inline {
                    %89 = fir.load %66#0 : !fir.ref<i32>
                    %c3_i32 = arith.constant 3 : i32
                    %90 = arith.subi %89, %c3_i32 overflow<nsw> : i32
                    %91 = fir.load %66#0 : !fir.ref<i32>
                    %c3_i32_9 = arith.constant 3 : i32
                    %92 = arith.addi %91, %c3_i32_9 overflow<nsw> : i32
                    %c1_i32_10 = arith.constant 1 : i32
                    %93 = arith.subi %92, %90 : i32
                    %94 = arith.addi %93, %c1_i32_10 : i32
                    %95 = arith.divsi %94, %c1_i32_10 : i32
                    fir.store %95 to %65 : !fir.ref<i32>
                    fir.store %90 to %69#0 : !fir.ref<i32>
                    cf.br ^bb1
                  ^bb1:  // 2 preds: ^bb0, ^bb10
                    %96 = fir.load %65 : !fir.ref<i32>
                    %c0_i32_11 = arith.constant 0 : i32
                    %97 = arith.cmpi sgt, %96, %c0_i32_11 : i32
                    cf.cond_br %97, ^bb2, ^bb11
                  ^bb2:  // pred: ^bb1
                    %98 = fir.load %67#0 : !fir.ref<i32>
                    %c3_i32_12 = arith.constant 3 : i32
                    %99 = arith.subi %98, %c3_i32_12 overflow<nsw> : i32
                    %100 = fir.load %67#0 : !fir.ref<i32>
                    %c3_i32_13 = arith.constant 3 : i32
                    %101 = arith.addi %100, %c3_i32_13 overflow<nsw> : i32
                    %c1_i32_14 = arith.constant 1 : i32
                    %102 = arith.subi %101, %99 : i32
                    %103 = arith.addi %102, %c1_i32_14 : i32
                    %104 = arith.divsi %103, %c1_i32_14 : i32
                    fir.store %104 to %64 : !fir.ref<i32>
                    fir.store %99 to %70#0 : !fir.ref<i32>
                    cf.br ^bb3
                  ^bb3:  // 2 preds: ^bb2, ^bb9
                    %105 = fir.load %64 : !fir.ref<i32>
                    %c0_i32_15 = arith.constant 0 : i32
                    %106 = arith.cmpi sgt, %105, %c0_i32_15 : i32
                    cf.cond_br %106, ^bb4, ^bb10
                  ^bb4:  // pred: ^bb3
                    %107 = fir.load %68#0 : !fir.ref<i32>
                    %c3_i32_16 = arith.constant 3 : i32
                    %108 = arith.subi %107, %c3_i32_16 overflow<nsw> : i32
                    %109 = fir.load %68#0 : !fir.ref<i32>
                    %c3_i32_17 = arith.constant 3 : i32
                    %110 = arith.addi %109, %c3_i32_17 overflow<nsw> : i32
                    %c1_i32_18 = arith.constant 1 : i32
                    %111 = arith.subi %110, %108 : i32
                    %112 = arith.addi %111, %c1_i32_18 : i32
                    %113 = arith.divsi %112, %c1_i32_18 : i32
                    fir.store %113 to %63 : !fir.ref<i32>
                    fir.store %108 to %71#0 : !fir.ref<i32>
                    cf.br ^bb5
                  ^bb5:  // 2 preds: ^bb4, ^bb8
                    %114 = fir.load %63 : !fir.ref<i32>
                    %c0_i32_19 = arith.constant 0 : i32
                    %115 = arith.cmpi sgt, %114, %c0_i32_19 : i32
                    cf.cond_br %115, ^bb6, ^bb9
                  ^bb6:  // pred: ^bb5
                    %116 = hlfir.designate %62#0{"sf"}   {fortran_attrs = #fir.var_attrs<pointer>} : (!fir.ref<!fir.type<_QMm_reproTinteger_field{sf:!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>}>>) -> !fir.ref<!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>>
                    %117 = fir.load %116 : !fir.ref<!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>>
                    %118 = fir.load %69#0 : !fir.ref<i32>
                    %119 = fir.convert %118 : (i32) -> i64
                    %120 = fir.load %70#0 : !fir.ref<i32>
                    %121 = fir.convert %120 : (i32) -> i64
                    %122 = fir.load %71#0 : !fir.ref<i32>
                    %123 = fir.convert %122 : (i32) -> i64
                    %124 = hlfir.designate %117 (%119, %121, %123)  : (!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>, i64, i64, i64) -> !fir.ref<i32>
                    %125 = fir.load %124 : !fir.ref<i32>
                    %c0_i32_20 = arith.constant 0 : i32
                    %126 = arith.cmpi eq, %125, %c0_i32_20 : i32
                    cf.cond_br %126, ^bb7, ^bb8
                  ^bb7:  // pred: ^bb6
                    %true = arith.constant true
                    %127 = fir.convert %true : (i1) -> !fir.logical<4>
                    hlfir.assign %127 to %72#0 : !fir.logical<4>, !fir.ref<!fir.logical<4>>
                    cf.br ^bb11
                  ^bb8:  // pred: ^bb6
                    %128 = fir.load %63 : !fir.ref<i32>
                    %c1_i32_21 = arith.constant 1 : i32
                    %129 = arith.subi %128, %c1_i32_21 : i32
                    fir.store %129 to %63 : !fir.ref<i32>
                    %130 = fir.load %71#0 : !fir.ref<i32>
                    %c1_i32_22 = arith.constant 1 : i32
                    %131 = arith.addi %130, %c1_i32_22 overflow<nsw> : i32
                    fir.store %131 to %71#0 : !fir.ref<i32>
                    cf.br ^bb5
                  ^bb9:  // pred: ^bb5
                    %132 = fir.load %64 : !fir.ref<i32>
                    %c1_i32_23 = arith.constant 1 : i32
                    %133 = arith.subi %132, %c1_i32_23 : i32
                    fir.store %133 to %64 : !fir.ref<i32>
                    %134 = fir.load %70#0 : !fir.ref<i32>
                    %c1_i32_24 = arith.constant 1 : i32
                    %135 = arith.addi %134, %c1_i32_24 overflow<nsw> : i32
                    fir.store %135 to %70#0 : !fir.ref<i32>
                    cf.br ^bb3
                  ^bb10:  // pred: ^bb3
                    %136 = fir.load %65 : !fir.ref<i32>
                    %c1_i32_25 = arith.constant 1 : i32
                    %137 = arith.subi %136, %c1_i32_25 : i32
                    fir.store %137 to %65 : !fir.ref<i32>
                    %138 = fir.load %69#0 : !fir.ref<i32>
                    %c1_i32_26 = arith.constant 1 : i32
                    %139 = arith.addi %138, %c1_i32_26 overflow<nsw> : i32
                    fir.store %139 to %69#0 : !fir.ref<i32>
                    cf.br ^bb1
                  ^bb11:  // 2 preds: ^bb1, ^bb7
                    scf.yield
                  }
                  %87 = fir.load %72#0 : !fir.ref<!fir.logical<4>>
                  %88 = fir.convert %87 : (!fir.logical<4>) -> i1
                  fir.if %88 {
                    %c1_i32_9 = arith.constant 1 : i32
                    omp.atomic.capture memory_order(relaxed) {
                      omp.atomic.update %52#0 : !fir.ref<i32> {
                      ^bb0(%arg24: i32):
                        %162 = arith.addi %arg24, %c1_i32_9 : i32
                        omp.yield(%162 : i32)
                      } atomic_control <>
                      omp.atomic.read %73#0 = %52#0 : !fir.ref<i32>, !fir.ref<i32>, i32
                    }
                    %c3 = arith.constant 3 : index
                    %c1_10 = arith.constant 1 : index
                    %c1_11 = arith.constant 1 : index
                    %89 = fir.allocmem !fir.array<3xi32> {bindc_name = ".tmp.arrayctor", uniq_name = ""}
                    %90 = fir.shape %c3 : (index) -> !fir.shape<1>
                    %91:2 = hlfir.declare %89(%90) {uniq_name = ".tmp.arrayctor"} : (!fir.heap<!fir.array<3xi32>>, !fir.shape<1>) -> (!fir.heap<!fir.array<3xi32>>, !fir.heap<!fir.array<3xi32>>)
                    %92 = fir.load %66#0 : !fir.ref<i32>
                    %93 = arith.addi %c1_10, %c1_11 : index
                    %94 = hlfir.designate %91#0 (%c1_10)  : (!fir.heap<!fir.array<3xi32>>, index) -> !fir.ref<i32>
                    hlfir.assign %92 to %94 : i32, !fir.ref<i32>
                    %95 = fir.load %67#0 : !fir.ref<i32>
                    %96 = arith.addi %93, %c1_11 : index
                    %97 = hlfir.designate %91#0 (%93)  : (!fir.heap<!fir.array<3xi32>>, index) -> !fir.ref<i32>
                    hlfir.assign %95 to %97 : i32, !fir.ref<i32>
                    %98 = fir.load %68#0 : !fir.ref<i32>
                    %99 = hlfir.designate %91#0 (%96)  : (!fir.heap<!fir.array<3xi32>>, index) -> !fir.ref<i32>
                    hlfir.assign %98 to %99 : i32, !fir.ref<i32>
                    %true = arith.constant true
                    %100 = hlfir.as_expr %91#0 move %true : (!fir.heap<!fir.array<3xi32>>, i1) -> !hlfir.expr<3xi32>
                    %101 = fir.load %51#0 : !fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>
                    %102 = fir.load %73#0 : !fir.ref<i32>
                    %103 = fir.convert %102 : (i32) -> i64
                    %104 = hlfir.designate %101 (%103)  : (!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>, i64) -> !fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>
                    %c3_12 = arith.constant 3 : index
                    %105 = fir.shape %c3_12 : (index) -> !fir.shape<1>
                    %106 = hlfir.designate %104{"loc"}   shape %105 : (!fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>, !fir.shape<1>) -> !fir.ref<!fir.array<3xi32>>
                    hlfir.assign %100 to %106 : !hlfir.expr<3xi32>, !fir.ref<!fir.array<3xi32>>
                    hlfir.destroy %100 : !hlfir.expr<3xi32>
                    %107 = hlfir.designate %62#0{"sf"}   {fortran_attrs = #fir.var_attrs<pointer>} : (!fir.ref<!fir.type<_QMm_reproTinteger_field{sf:!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>}>>) -> !fir.ref<!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>>
                    %108 = fir.load %107 : !fir.ref<!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>>
                    %109 = fir.load %66#0 : !fir.ref<i32>
                    %110 = fir.convert %109 : (i32) -> i64
                    %111 = fir.load %67#0 : !fir.ref<i32>
                    %112 = fir.convert %111 : (i32) -> i64
                    %113 = fir.load %68#0 : !fir.ref<i32>
                    %114 = fir.convert %113 : (i32) -> i64
                    %115 = hlfir.designate %108 (%110, %112, %114)  : (!fir.box<!fir.ptr<!fir.array<?x?x?xi32>>>, i64, i64, i64) -> !fir.ref<i32>
                    %116 = fir.load %115 : !fir.ref<i32>
                    hlfir.assign %116 to %74#0 : i32, !fir.ref<i32>
                    %117 = fir.load %74#0 : !fir.ref<i32>
                    %118 = fir.load %51#0 : !fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>
                    %119 = fir.load %73#0 : !fir.ref<i32>
                    %120 = fir.convert %119 : (i32) -> i64
                    %121 = hlfir.designate %118 (%120)  : (!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>, i64) -> !fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>
                    %122 = hlfir.designate %121{"ib_patch_id"}   : (!fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>) -> !fir.ref<i32>
                    hlfir.assign %117 to %122 : i32, !fir.ref<i32>
                    %c0_i32_13 = arith.constant 0 : i32
                    %123 = fir.load %51#0 : !fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>
                    %124 = fir.load %73#0 : !fir.ref<i32>
                    %125 = fir.convert %124 : (i32) -> i64
                    %126 = hlfir.designate %123 (%125)  : (!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>, i64) -> !fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>
                    %127 = hlfir.designate %126{"x_periodicity"}   : (!fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>) -> !fir.ref<i32>
                    hlfir.assign %c0_i32_13 to %127 : i32, !fir.ref<i32>
                    %c0_i32_14 = arith.constant 0 : i32
                    %128 = fir.load %51#0 : !fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>
                    %129 = fir.load %73#0 : !fir.ref<i32>
                    %130 = fir.convert %129 : (i32) -> i64
                    %131 = hlfir.designate %128 (%130)  : (!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>, i64) -> !fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>
                    %132 = hlfir.designate %131{"y_periodicity"}   : (!fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>) -> !fir.ref<i32>
                    hlfir.assign %c0_i32_14 to %132 : i32, !fir.ref<i32>
                    %c0_i32_15 = arith.constant 0 : i32
                    %133 = fir.load %51#0 : !fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>
                    %134 = fir.load %73#0 : !fir.ref<i32>
                    %135 = fir.convert %134 : (i32) -> i64
                    %136 = hlfir.designate %133 (%135)  : (!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>, i64) -> !fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>
                    %137 = hlfir.designate %136{"z_periodicity"}   : (!fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>) -> !fir.ref<i32>
                    hlfir.assign %c0_i32_15 to %137 : i32, !fir.ref<i32>
                    %false_16 = arith.constant false
                    %138 = fir.convert %false_16 : (i1) -> !fir.logical<4>
                    %139 = fir.load %51#0 : !fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>
                    %140 = fir.load %73#0 : !fir.ref<i32>
                    %141 = fir.convert %140 : (i32) -> i64
                    %142 = hlfir.designate %139 (%141)  : (!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>, i64) -> !fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>
                    %143 = hlfir.designate %142{"slip"}   : (!fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>) -> !fir.ref<!fir.logical<4>>
                    hlfir.assign %138 to %143 : !fir.logical<4>, !fir.ref<!fir.logical<4>>
                    %c0_i32_17 = arith.constant 0 : i32
                    %144 = fir.load %51#0 : !fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>
                    %145 = fir.load %73#0 : !fir.ref<i32>
                    %146 = fir.convert %145 : (i32) -> i64
                    %147 = hlfir.designate %144 (%146)  : (!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>, i64) -> !fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>
                    %c3_18 = arith.constant 3 : index
                    %148 = fir.shape %c3_18 : (index) -> !fir.shape<1>
                    %c1_19 = arith.constant 1 : index
                    %149 = hlfir.designate %147{"db"} <%148> (%c1_19)  : (!fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>, !fir.shape<1>, index) -> !fir.ref<i32>
                    hlfir.assign %c0_i32_17 to %149 : i32, !fir.ref<i32>
                    %c0_i32_20 = arith.constant 0 : i32
                    %150 = fir.load %51#0 : !fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>
                    %151 = fir.load %73#0 : !fir.ref<i32>
                    %152 = fir.convert %151 : (i32) -> i64
                    %153 = hlfir.designate %150 (%152)  : (!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>, i64) -> !fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>
                    %c3_21 = arith.constant 3 : index
                    %154 = fir.shape %c3_21 : (index) -> !fir.shape<1>
                    %c2 = arith.constant 2 : index
                    %155 = hlfir.designate %153{"db"} <%154> (%c2)  : (!fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>, !fir.shape<1>, index) -> !fir.ref<i32>
                    hlfir.assign %c0_i32_20 to %155 : i32, !fir.ref<i32>
                    %c0_i32_22 = arith.constant 0 : i32
                    %156 = fir.load %51#0 : !fir.ref<!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>>
                    %157 = fir.load %73#0 : !fir.ref<i32>
                    %158 = fir.convert %157 : (i32) -> i64
                    %159 = hlfir.designate %156 (%158)  : (!fir.box<!fir.heap<!fir.array<?x!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>>>, i64) -> !fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>
                    %c3_23 = arith.constant 3 : index
                    %160 = fir.shape %c3_23 : (index) -> !fir.shape<1>
                    %c3_24 = arith.constant 3 : index
                    %161 = hlfir.designate %159{"db"} <%160> (%c3_24)  : (!fir.ref<!fir.type<_QMm_reproTghost_point{loc:!fir.array<3xi32>,ip_loc:!fir.array<3xf64>,ip_grid:!fir.array<3xi32>,interp_coeffs:!fir.array<2x2x2xf64>,interp_valid:!fir.logical<4>,ib_patch_id:i32,levelset:f64,levelset_norm:!fir.array<3xf64>,slip:!fir.logical<4>,db:!fir.array<3xi32>,x_periodicity:i32,y_periodicity:i32,z_periodicity:i32}>>, !fir.shape<1>, index) -> !fir.ref<i32>
                    hlfir.assign %c0_i32_22 to %161 : i32, !fir.ref<i32>
                  }
                }
                omp.yield
              }
            } {omp.composite}
          } {omp.composite}
          omp.terminator
        } {omp.composite}
        omp.terminator
      } {omp.combined}
      omp.terminator
    } {omp.combined}
    return
  }
}
