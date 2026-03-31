#!/bin/bash
# Real discovery: httpbin — simple API
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

echo "  site2cli — Real API Discovery (httpbin)"
echo "  ========================================="
sleep 1

site2cli sites remove httpbin.org 2>/dev/null || true
sleep 0.3

type_cmd "site2cli discover https://httpbin.org/ --no-enhance"

sleep 0.5

type_cmd "site2cli sites show httpbin.org"

sleep 0.5

echo ""
echo "  # Get your IP address via discovered API"
sleep 0.3
type_cmd "site2cli run httpbin.org returns_the_client\\'s_ip_address_information --json"

sleep 2
