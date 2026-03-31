#!/bin/bash
# Real discovery: PokeAPI — full pipeline + run
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

echo "  site2cli — Real API Discovery (PokeAPI)"
echo "  ========================================="
sleep 1

# Clear old entry so discover runs fresh
site2cli sites remove pokeapi.co 2>/dev/null || true
sleep 0.3

# Discover with real browser
type_cmd "site2cli discover https://pokeapi.co/ --no-enhance"

sleep 0.5

# Show what was discovered
type_cmd "site2cli sites show pokeapi.co"

sleep 0.5

# Run a discovered action
echo ""
echo "  # Execute a discovered action against the real API"
sleep 0.3
type_cmd "site2cli run pokeapi.co get_api_v2_pokemon_ditto --keys-only --json"

sleep 2
