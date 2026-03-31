#!/bin/bash
# Demo: API Discovery + Run
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

echo "  site2cli — Discovery & Execution"
echo "  ================================="
sleep 1

type_cmd "site2cli sites list"
sleep 0.5

echo ""
echo "  # Run an action against httpbin.org"
sleep 0.5
type_cmd "site2cli run httpbin.org returns_the_client\\'s_ip_address_information --json"
sleep 0.5

echo ""
echo "  # Fetch posts from JSONPlaceholder"
sleep 0.5
type_cmd "site2cli run jsonplaceholder.typicode.com retrieves_a_list_of_all_posts_from_the_system --limit 3 --json"
sleep 0.5

echo ""
echo "  # Get Pokemon data from PokeAPI"
sleep 0.5
type_cmd "site2cli run pokeapi.co get_api_v2_pokemon_ditto --keys-only --json"
sleep 1.5
