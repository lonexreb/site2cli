#!/bin/bash
# Demo: Full CLI Overview
set -e
D=0.02

type_cmd() {
    echo ""
    echo -n "$ "
    for ((i=0; i<${#1}; i++)); do echo -n "${1:$i:1}"; sleep $D; done
    echo ""
    sleep 0.2
    eval "$1"
    sleep 1
}

echo "  site2cli — Full CLI Overview"
echo "  =============================="
sleep 1

type_cmd "site2cli --help"
sleep 1

type_cmd "site2cli version"
sleep 1.5
