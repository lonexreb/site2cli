#!/bin/bash
# Real discovery: JSONPlaceholder — auto-probe on static homepage
set -e
D=0.03

type_cmd() {
    echo ""
    echo -n "$ "
    for ((i=0; i<${#1}; i++)); do echo -n "${1:$i:1}"; sleep $D; done
    echo ""
    sleep 0.3
    eval "$1"
    sleep 1.5
}

echo "  site2cli — Real API Discovery (JSONPlaceholder)"
echo "  ================================================="
echo "  Auto-probes REST links on static homepage"
sleep 1

site2cli sites remove jsonplaceholder.typicode.com 2>/dev/null || true
sleep 0.3

type_cmd "site2cli discover https://jsonplaceholder.typicode.com/ --no-enhance"

sleep 0.5

type_cmd "site2cli sites show jsonplaceholder.typicode.com"

sleep 0.5

echo ""
echo "  # Fetch real posts from the discovered API"
sleep 0.3
type_cmd "site2cli run jsonplaceholder.typicode.com retrieves_a_list_of_all_posts_from_the_system --limit 2 --json"

sleep 2
