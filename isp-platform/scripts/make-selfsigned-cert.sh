#!/bin/sh
# Self-signed cert for a LAN-only install. Use your internal CA if you have one.
set -e
cd "$(dirname "$0")/.." && mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=${1:-isp-platform.local}" \
  -keyout certs/privkey.pem -out certs/fullchain.pem
chmod 600 certs/privkey.pem
echo "certs/fullchain.pem + certs/privkey.pem written"
