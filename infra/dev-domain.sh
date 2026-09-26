#!/usr/bin/env bash
# Switch the dev stack between *.localhost (this Mac only) and <lan-ip>.nip.io (phones and other
# devices on the same Wi-Fi). Dev only: writes infra/dev-domain.env (git-ignored), which Compose
# layers over .env for the app containers, then recreates them.
#
#   infra/dev-domain.sh lan         # detect this Mac's LAN IP and use <ip-with-dashes>.nip.io
#   infra/dev-domain.sh localhost   # back to *.localhost
set -euo pipefail

cd "$(dirname "$0")/.."
MODE="${1:-}"
OUT="infra/dev-domain.env"
COMPOSE=(docker compose -f infra/docker-compose.yml)

lan_ip() {
  # The interface that carries the default route (Wi-Fi or Ethernet), then its IPv4 address.
  local iface ip
  iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}' || true)"
  if [[ -n "$iface" ]]; then ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"; fi
  if [[ -z "${ip:-}" ]]; then  # Linux
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") print $(i+1)}' || true)"
  fi
  if [[ -z "${ip:-}" ]]; then ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"; fi
  echo "${ip:-}"
}

case "$MODE" in
  lan)
    IP="$(lan_ip)"
    if [[ ! "$IP" =~ ^(10|172|192)\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      echo "Couldn't find a private LAN IP (got '${IP}'). Are you on Wi-Fi?" >&2
      exit 1
    fi
    DOMAIN="${IP//./-}.nip.io"
    ASSETS="http://${IP}:8333"
    ;;
  localhost)
    DOMAIN="localhost"
    ASSETS="http://localhost:8333"
    ;;
  *)
    echo "Usage: $0 lan|localhost" >&2
    exit 2
    ;;
esac

cat > "$OUT" <<EOF
# Written by infra/dev-domain.sh ($MODE) — dev only, git-ignored. Remove it or run
# "make localhost" to go back to *.localhost.
PLATFORM_DOMAIN=$DOMAIN
S3_PUBLIC_ENDPOINT_URL=$ASSETS
EOF
echo "Platform domain: $DOMAIN (photos from $ASSETS)"

# Recreate what changed (the app containers read the new domain); data volumes are kept.
"${COMPOSE[@]}" up -d --quiet-pull >/dev/null 2>&1
echo "Waiting for the web server…"
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "http://localhost:3000/health/live" 2>/dev/null; then break; fi
  sleep 2
done
# Cached public branding holds image links built for the old address.
"${COMPOSE[@]}" exec -T backend python manage.py shell -c "from django.core.cache import cache; cache.clear()" >/dev/null 2>&1 || true

WEB="http://%s:3000"
echo
echo "Open these (password staff-dev-password for staff, code 123456 for shops):"
printf "  Main site (shop chooser)   $WEB/login\n" "$DOMAIN"
printf "  Platform admin             $WEB/login\n" "admin.$DOMAIN"
printf "  Sharma staff               $WEB/login\n" "sharma.$DOMAIN"
printf "  Sharma shop                $WEB/shop/login\n" "sharma.$DOMAIN"
printf "  Patel staff                $WEB/login\n" "patel.$DOMAIN"
printf "  Patel shop                 $WEB/shop/login\n" "patel.$DOMAIN"
if [[ "$MODE" == "lan" ]]; then
  echo
  echo "Your phone must be on the same Wi-Fi. Switch back with: make localhost"
fi
