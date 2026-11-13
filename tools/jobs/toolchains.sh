# generated from catalog/toolchains.yaml by tools/derive/toolchains_gen.py; do not edit
# The toolchain table the job scripts source (`. tools/jobs/toolchains.sh`): the
# toolchains per lane (the runner group a script belongs to), per machine
# (measured; a regression release is not one) and per family, and
# `tc_check NAME LANE`, which refuses a toolchain the lane does not run.
TC_ALL="afar cce19 cce20 cce21 cce21_4 afar_g90 cce19_g90 cce20_g90 cce21_g90 afar_mi300x afar_mi350x nvhpc nvhpc269 gcc gcc_g90 gcc_mi300x gcc_mi350x gcc_sm80"
TC_LANE_tuolumne="afar cce19 cce20 cce21 cce21_4"
TC_LANE_tioga="afar_g90 cce19_g90 cce20_g90 cce21_g90"
TC_LANE_mi300x="afar_mi300x gcc_mi300x"
TC_LANE_mi350x="afar_mi350x gcc_mi350x"
TC_LANE_wingtip="nvhpc nvhpc269"
TC_LANE_gcc="gcc gcc_g90 gcc_sm80"
TC_MACHINE_tuolumne="afar cce19 cce20 cce21 gcc"
TC_MACHINE_tioga="afar_g90 cce19_g90 cce20_g90 cce21_g90 gcc_g90"
TC_MACHINE_mi300x="afar_mi300x gcc_mi300x"
TC_MACHINE_mi350x="afar_mi350x gcc_mi350x"
TC_MACHINE_wingtip="nvhpc nvhpc269 gcc_sm80"
TC_FAMILY_afar="afar afar_g90 afar_mi300x afar_mi350x"
TC_FAMILY_cce="cce19 cce20 cce21 cce21_4 cce19_g90 cce20_g90 cce21_g90"
TC_FAMILY_nvhpc="nvhpc nvhpc269"
TC_FAMILY_gcc="gcc gcc_g90 gcc_mi300x gcc_mi350x gcc_sm80"
TC_REGRESSION="cce21_4"
tc_machine() {  # the machine of a toolchain
  case "$1" in
    afar|cce19|cce20|cce21|cce21_4|gcc) echo "tuolumne" ;;
    afar_g90|cce19_g90|cce20_g90|cce21_g90|gcc_g90) echo "tioga" ;;
    afar_mi300x|gcc_mi300x) echo "mi300x" ;;
    afar_mi350x|gcc_mi350x) echo "mi350x" ;;
    nvhpc|nvhpc269|gcc_sm80) echo "wingtip" ;;
    *) return 1 ;;
  esac
}
tc_family() {  # the compiler family of a toolchain
  case "$1" in
    afar|afar_g90|afar_mi300x|afar_mi350x) echo "afar" ;;
    cce19|cce20|cce21|cce21_4|cce19_g90|cce20_g90|cce21_g90) echo "cce" ;;
    nvhpc|nvhpc269) echo "nvhpc" ;;
    gcc|gcc_g90|gcc_mi300x|gcc_mi350x|gcc_sm80) echo "gcc" ;;
    *) return 1 ;;
  esac
}
tc_modes() {  # the stored row keys of its memory modes
  case "$1" in
    afar|cce19|cce20|cce21|cce21_4|gcc) echo "0 1" ;;
    afar_g90|cce19_g90|cce20_g90|cce21_g90|afar_mi300x|afar_mi350x|gcc_g90|gcc_mi300x|gcc_mi350x|gcc_sm80) echo "0" ;;
    nvhpc|nvhpc269) echo "0 2" ;;
    *) return 1 ;;
  esac
}
tc_lane() {  # the lane (runner group) of a toolchain
  case "$1" in
    afar|cce19|cce20|cce21|cce21_4) echo "tuolumne" ;;
    afar_g90|cce19_g90|cce20_g90|cce21_g90) echo "tioga" ;;
    afar_mi300x|gcc_mi300x) echo "mi300x" ;;
    afar_mi350x|gcc_mi350x) echo "mi350x" ;;
    nvhpc|nvhpc269) echo "wingtip" ;;
    gcc|gcc_g90|gcc_sm80) echo "gcc" ;;
    *) return 1 ;;
  esac
}
tc_list() {  # tc_list LANE [MACHINE]: the lane's toolchains (on MACHINE), comma-separated
  local v out="" t; eval "v=\${TC_LANE_$1-}"
  [ -n "$v" ] || { echo "unknown lane $1 (lanes: tuolumne tioga mi300x mi350x wingtip gcc)" >&2; return 1; }
  for t in $v; do [ -z "${2:-}" ] || [ "$(tc_machine "$t")" = "$2" ] || continue; out="${out:+$out,}$t"; done
  echo "$out"
}
tc_check() {  # tc_check NAME LANE: 0 when NAME is a toolchain of LANE, else a message and 1
  local lane; lane=$(tc_lane "$1") || { echo "unknown toolchain $1 (catalog/toolchains.yaml); known: $TC_ALL" >&2; return 1; }
  if [ "$lane" != "$2" ]; then
    local v; eval "v=\${TC_LANE_$2-}"
    [ -n "$v" ] || { echo "unknown lane $2 (lanes: tuolumne tioga mi300x mi350x wingtip gcc)" >&2; return 1; }
    echo "toolchain $1 is not run by the $2 scripts (its lane: $lane); this lane runs: $v" >&2; return 1
  fi
}
