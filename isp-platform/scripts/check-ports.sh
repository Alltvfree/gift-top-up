#!/bin/sh
# Pre-flight on the target server: are the host ports in .env free, and does the Docker subnet clash?
# Usage: ./scripts/check-ports.sh   (reads .env, falls back to defaults)
cd "$(dirname "$0")/.." || exit 1
get() { v=$(grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//; s/[[:space:]]*$//'); echo "${v:-$2}"; }
HTTPS_PORT=$(get HTTPS_PORT 8443); HTTP_PORT=$(get HTTP_PORT 8081); API_LOCAL_PORT=$(get API_LOCAL_PORT 8000)
RADIUS_AUTH_PORT=$(get RADIUS_AUTH_PORT 1812); RADIUS_ACCT_PORT=$(get RADIUS_ACCT_PORT 1813); DOCKER_SUBNET=$(get DOCKER_SUBNET 172.31.250.0/24)
bad=0
if ! command -v ss >/dev/null 2>&1; then
  echo "Cannot check ports: 'ss' not found (sudo apt install iproute2)."; exit 2
fi
check() { # proto port label
  if ss -H -l -n "-$1" "sport = :$2" 2>/dev/null | grep -q .; then
    echo "  BUSY  $1/$2  ($3) — used by: $(ss -H -l -n -p "-$1" "sport = :$2" 2>/dev/null | grep -o 'users:(("[^"]*"' | head -1 | cut -d'"' -f2)"
    bad=1
  else echo "  free  $1/$2  ($3)"; fi
}
echo "Host ports:"
check t "$HTTPS_PORT" "HTTPS_PORT web UI"
check t "$HTTP_PORT" "HTTP_PORT redirect"
check t "$API_LOCAL_PORT" "API_LOCAL_PORT"
check u "$RADIUS_AUTH_PORT" "RADIUS_AUTH_PORT"
check u "$RADIUS_ACCT_PORT" "RADIUS_ACCT_PORT"
echo "Docker subnet $DOCKER_SUBNET:"
net=${DOCKER_SUBNET%/*}; pre=$(echo "$net" | cut -d. -f1-3)
if ip -4 route 2>/dev/null | grep -v "br-\|docker" | grep -q "^$pre\."; then
  echo "  CLASH  a route for $pre.x already exists on this host:"; ip -4 route | grep "^$pre\." | sed 's/^/    /'; bad=1
elif docker network ls -q 2>/dev/null | xargs -r docker network inspect -f '{{.Name}} {{range .IPAM.Config}}{{.Subnet}}{{end}}' 2>/dev/null | grep -v "^isp-platform_" | grep -q " $pre\."; then
  echo "  CLASH  another Docker network uses $pre.x"; bad=1
else echo "  ok"; fi
[ $bad -eq 0 ] && echo "All clear." || echo "Change the values above in .env, then re-run."
exit $bad
