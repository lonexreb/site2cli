#!/bin/bash
# Scripted demo for site2cli — records an asciinema cast file
# Usage: asciinema rec --command="bash scripts/record_demo.sh" assets/demo.cast

set -e

TYPE_DELAY=0.03

type_cmd() {
    echo ""
    echo -n "$ "
    for ((i=0; i<${#1}; i++)); do
        echo -n "${1:$i:1}"
        sleep $TYPE_DELAY
    done
    echo ""
    sleep 0.3
    eval "$1"
    sleep 1.5
}

echo "╔═══════════════════════════════════════════════╗"
echo "║  site2cli — Turn any website into a CLI/API  ║"
echo "╠═══════════════════════════════════════════════╣"
echo "║  Auto-discover APIs, generate CLIs & MCP     ║"
echo "╚═══════════════════════════════════════════════╝"
sleep 2

# 1. Show version
type_cmd "site2cli version"

# 2. List discovered sites
type_cmd "site2cli sites list"

# 3. Run an action
type_cmd "site2cli run httpbin.org returns_the_client\'s_ip_address_information --json"

# 4. Run another
type_cmd "site2cli run jsonplaceholder.typicode.com retrieves_a_list_of_all_posts_from_the_system --limit 3 --json"

# 5. Export for community sharing
type_cmd "site2cli community export jsonplaceholder.typicode.com"

echo ""
echo "Done! Sites discovered, actions executed, specs shared."
sleep 2
