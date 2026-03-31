#!/bin/bash
# Demo: MCP Server for Claude Code
set -e
D=0.02

type_cmd() {
    echo ""
    echo -n "$ "
    for ((i=0; i<${#1}; i++)); do echo -n "${1:$i:1}"; sleep $D; done
    echo ""
    sleep 0.2
}

echo "  site2cli — MCP Server for AI Agents"
echo "  ======================================"
sleep 1

echo "  # Add site2cli as an MCP server for Claude Code"
sleep 0.5
type_cmd "claude mcp add site2cli -- uvx --from 'site2cli[mcp]' site2cli --mcp"
echo "  Added stdio MCP server site2cli"
sleep 1

echo ""
echo "  # Show discovered sites available as MCP tools"
sleep 0.5
type_cmd "site2cli sites list"
eval "site2cli sites list"
sleep 0.5

echo ""
echo "  # Claude Code can now call any discovered API as a tool:"
echo '  > "Use site2cli to get data about Pokemon Ditto"'
echo '  > "Use site2cli to list all JSONPlaceholder posts"'
echo '  > "Use site2cli to get my IP from httpbin"'
sleep 2
