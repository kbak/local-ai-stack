#!/bin/bash
set -e

BACKENDS=/opt/swarmui/Data/Backends.fds

# Ensure --highvram is set so Flux stays resident in VRAM between generations.
if [ -f "$BACKENDS" ]; then
    sed -i 's/\t\tExtraArgs: \\x/\t\tExtraArgs: --highvram/' "$BACKENDS"
    sed -i 's/\t\tExtraArgs: $/\t\tExtraArgs: --highvram/' "$BACKENDS"
    # Idempotent: if already set, leave it.
fi

exec bash launch-linux.sh "$@"
