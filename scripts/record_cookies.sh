#!/bin/bash
# Demo: Cookie Management
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

echo "  site2cli — Cookie Management"
echo "  =============================="
sleep 1

type_cmd "site2cli cookies set example.com session_id abc123 --secure"

type_cmd "site2cli cookies set example.com csrf_token xyz789"

type_cmd "site2cli cookies list example.com"
sleep 0.5

type_cmd "site2cli cookies clear example.com"

type_cmd "site2cli cookies list example.com"
sleep 1.5
