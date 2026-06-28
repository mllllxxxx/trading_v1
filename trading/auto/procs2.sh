#!/bin/sh
for p in $(ls /proc 2>/dev/null | grep -E '^[0-9]+$'); do
    echo -n "PID $p: "
    cat /proc/$p/cmdline 2>/dev/null | tr '\0' ' '
    echo
done
