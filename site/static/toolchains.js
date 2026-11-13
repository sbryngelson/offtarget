// generated from catalog/toolchains.yaml by tools/derive/toolchains_gen.py; do not edit
// The toolchains the site knows: the family buttons (the first is the default), the
// version pills of each family and their toolchain ids, the GPU/mode columns per family,
// the family and target names, the ISA of each target, the feature-support rows and the
// targets each row ran on.
const FAMILIES = ['cce', 'afar', 'nvhpc', 'gcc'];
const VERSIONS = { cce: ['19.0.0', '20.0.2', '21.0.3', '21.0.4'], afar: ['AFAR 24.3.0'], nvhpc: ['25.11', '26.9'], gcc: ['16.2 AMD', '16.2 A100'] };
const TC = { '19.0.0': 'cce19', '20.0.2': 'cce20', '21.0.3': 'cce21', '21.0.4': 'cce21_4', 'AFAR 24.3.0': 'afar', '25.11': 'nvhpc', '26.9': 'nvhpc269', '16.2 AMD': 'gcc', '16.2 A100': 'gcc_sm80' };
const TARGETS = { cce: ['mi300a-u', 'mi300a-c', 'mi250x', 'mi300x', 'mi350x'], afar: ['mi300a-u', 'mi300a-c', 'mi250x', 'mi300x', 'mi350x'], nvhpc: ['a100-s', 'a100-m'], gcc: ['mi300a-u', 'mi300a-c', 'mi250x', 'mi300x', 'mi350x', 'a100-s'] };
const FAM_NAME = { cce: 'Cray CCE (ftn, craycc)', afar: 'AMD AFAR (amdflang, amdclang)', nvhpc: 'NVIDIA HPC SDK (nvfortran, nvc)', gcc: 'GCC (gcc, gfortran)' };
const TG_NAME = { 'mi300a-u': 'MI300A (gfx942), unified memory (XNACK 1)', 'mi300a-c': 'MI300A (gfx942), copy (XNACK 0)', mi250x: 'MI250X (gfx90a), copy (XNACK 0)', mi300x: 'MI300X (gfx942), copy (XNACK 0)', mi350x: 'MI350X (gfx950), copy (XNACK 0)', 'a100-s': 'A100 (sm_80), separate memory', 'a100-m': 'A100 (sm_80), managed memory' };
const TG_SHORT = { 'mi300a-u': 'MI300A unified', 'mi300a-c': 'MI300A copy', mi250x: 'MI250X', mi300x: 'MI300X', mi350x: 'MI350X', 'a100-s': 'A100 separate', 'a100-m': 'A100 managed' };
const TG_ISA = { 'mi300a-u': 'gfx942', 'mi300a-c': 'gfx942', mi250x: 'gfx90a', mi300x: 'gfx942', mi350x: 'gfx950', 'a100-s': 'sm_80', 'a100-m': 'sm_80' };
const CU_TC = [['afar', 'AFAR 24.3.0'], ['cce19', 'CCE 19.0.0'], ['cce20', 'CCE 20.0.2'], ['cce21', 'CCE 21.0.3'], ['cce21_4', 'CCE 21.0.4'], ['nvhpc', 'NVHPC 25.11'], ['nvhpc269', 'NVHPC 26.9'], ['gcc', 'GCC 16.2.0 (AMD)'], ['gcc_sm80', 'GCC 16.2.0 (A100)']];
const CU_TG = { amd: [['mi300a-u', 'MI300A unified'], ['mi300a-c', 'MI300A copy'], ['mi250x', 'MI250X'], ['mi300x', 'MI300X'], ['mi350x', 'MI350X']], nvidia: [['a100-s', 'A100 separate'], ['a100-m', 'A100 managed']] };
const CU_KIND = { afar: 'amd', cce19: 'amd', cce20: 'amd', cce21: 'amd', cce21_4: 'amd', nvhpc: 'nvidia', nvhpc269: 'nvidia', gcc: 'amd', gcc_sm80: 'nvidia' };
const CU_RUN = { afar: ['mi300a-u', 'mi300a-c', 'mi250x', 'mi300x', 'mi350x'], cce19: ['mi300a-u', 'mi300a-c', 'mi250x'], cce20: ['mi300a-u', 'mi300a-c', 'mi250x'], cce21: ['mi300a-u', 'mi300a-c', 'mi250x'], cce21_4: ['mi300a-u', 'mi300a-c'], nvhpc: ['a100-s', 'a100-m'], nvhpc269: ['a100-s', 'a100-m'], gcc: ['mi300a-u', 'mi300a-c', 'mi250x', 'mi300x', 'mi350x'], gcc_sm80: ['a100-s'] };
if (typeof module !== 'undefined') module.exports = { FAMILIES, VERSIONS, TC, TARGETS, FAM_NAME, TG_NAME, TG_SHORT, TG_ISA, CU_TC, CU_TG, CU_KIND, CU_RUN };
