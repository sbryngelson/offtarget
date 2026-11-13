Source: ROCm/llvm-project commit 3ba19712e9fbf709f6c93d33394211ed4eeec8a7 (the AFAR 24.3.0 amdflang build), flang/docs/OpenMPSupport.md and flang/test/Lower/OpenMP/Todo/. The doc says the compiler's TODO / 'Not Yet Implemented' messages are authoritative and the status tables are only a reference. The source was fetched into corpus/rocm_llvm_afar (git-ignored).

This directory holds snapshots of every vendor document that a claim is read from.
catalog/vendor_claims.yaml lists them under `documents`, with their URL, origin
and version. `python3 -I tools/derive/claims.py ingest` checks every quote in
catalog/omp/claims.yaml and catalog/acc/claims.yaml against them.

- hpe-cce-<version>-intro_openmp.txt, -intro_openacc.txt: the man pages shipped
  with CCE 19.0.0, 20.0.2 and 21.0.3, rendered with
  `MANWIDTH=4000 man -l /opt/cray/pe/cce/<version>/man/man7/<page>.7 | col -bx`
  (one paragraph or bullet per line), on 2026-10-22.
- hpe-cce-<version>-release_info.txt: /opt/cray/pe/cce/<version>/release_info
  (for 19.0.0, for 20.0.0 standing in for the 20.0 series because 20.0.2 ships a placeholder, and for 21.0.3).
- olcf-frontier-guide-openacc.txt: the Compiling > OpenACC section of the OLCF
  Frontier User Guide (https://docs.olcf.ornl.gov/systems/frontier_user_guide.html).
- amdclang_afar_OpenMPSupport.md: clang/docs/OpenMPSupport.md at the AFAR commit
  (`git show 3ba19712...:clang/docs/OpenMPSupport.md`).
- rocm-docs-7.1.0-conceptual-openmp.txt: the ROCm 7.1.0 "OpenMP support" page,
  markup stripped (fetched with curl 2026-10-22).
- rocm-docs-7.1.1-clang20-OpenMPSupport.csv: the tables of the AMD-hosted
  Clang 20.0.0git OpenMPSupport page (fetched with curl 2026-10-22).
- nvidia-hpc-25.11-user-guide-openmp.txt, -openacc.txt, -memory.txt:
  chapters 7 (Using OpenMP; 7.4 OpenMP Subset), 6 (Using OpenACC; 6.1.3 OpenACC
  Support) and section 5.4 (Memory Model) of the NVIDIA HPC Compilers User's
  Guide of the installed release, 25.11
  (https://docs.nvidia.com/hpc-sdk/archive/25.11/compilers/hpc-compilers-user-guide/index.html),
  fetched with curl 2026-10-24, HTML stripped to one paragraph per line (list
  items as "- " bullets). The 25.11 release notes were read too. They state
  nothing about OpenMP or OpenACC features, so there is no snapshot of them.
