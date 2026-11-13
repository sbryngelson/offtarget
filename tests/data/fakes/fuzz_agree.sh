#!/bin/bash
# Fake fuzz program: checksum 42 everywhere; ran_on_host=1 only with
# OMP_TARGET_OFFLOAD=disabled.
if [ "$OMP_TARGET_OFFLOAD" = disabled ]; then h=1; else h=0; fi
echo "RESULT checksum=42 ran_on_host=$h"
