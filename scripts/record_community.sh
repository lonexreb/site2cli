#!/bin/bash
# Demo: Community Spec Sharing
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

echo "  site2cli — Community Spec Sharing"
echo "  ==================================="
sleep 1

echo "  # Export a discovered site as a shareable bundle"
sleep 0.5
type_cmd "site2cli community export jsonplaceholder.typicode.com"

echo ""
echo "  # Check the exported bundle"
sleep 0.3
type_cmd "ls -lh jsonplaceholder.typicode.com.site2cli.json"

echo ""
echo "  # List community specs"
sleep 0.3
type_cmd "site2cli community list"

echo ""
echo "  # Anyone can import: site2cli community import <file>"
sleep 1.5
