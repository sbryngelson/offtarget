#!/bin/bash
# Fake program: dies of SIGABRT (also without OMP_TARGET_OFFLOAD=mandatory).
echo "fake: memory access fault" >&2
kill -ABRT $$
