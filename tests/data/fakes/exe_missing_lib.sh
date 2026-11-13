#!/bin/bash
# Fake program: the dynamic loader cannot find a shared library (verbatim
# message from tests/data/messages/cce_run_no_rocm.txt), exit 127.
echo "./c2.out: error while loading shared libraries: libmpi_gtl_hsa.so.0: cannot open shared object file: No such file or directory" >&2
exit 127
