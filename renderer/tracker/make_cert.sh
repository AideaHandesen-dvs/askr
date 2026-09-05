#!/usr/bin/env bash
# tracker_server.py 用の自己署名証明書を作る(LAN内のスマホからHTTPSで開くため)。
#   ・SAN に「このPCのLAN IP」を必ず入れる。今のブラウザは CN を見ず SAN しか見ないため、
#     SAN が無い証明書は「詳細設定→アクセスする」を押しても弾かれることがある。
#   ・鍵は EC(prime256v1)。スマホのTLSハンドシェイクが RSA より軽い。
#   ・出力は certs/(gitignore 済み)。10年物＝運用中に切れて配信直前に慌てない。
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p certs

IP="${1:-$(hostname -I | awk '{print $1}')}"          # 引数でIP指定可(複数NICでズレた時用)
HOST="$(hostname -s)"
# スマホは「短い名前」ではなく検索ドメインを足した FQDN(例: host.lan)で引きに行くことがある。
# その名前がSANに無いと、警告が「自己署名」ではなく**名前不一致**に化けて原因が分かりにくくなる。
# ここで拾えるだけ拾って全部SANに入れる(重複は下で除く)。
NAMES="$HOST $HOST.local localhost"
FQDN="$(hostname -f 2>/dev/null || true)"
[ -n "$FQDN" ] && NAMES="$NAMES $FQDN"
for d in $(awk '/^(search|domain)/{for(i=2;i<=NF;i++)print $i}' /etc/resolv.conf 2>/dev/null); do
  NAMES="$NAMES $HOST.$d"
done
NAMES="$(echo "$NAMES" | tr ' ' '\n' | grep -v '^$' | sort -u | tr '\n' ' ')"
SAN="IP:$IP,IP:127.0.0.1$(for n in $NAMES; do printf ',DNS:%s' "$n"; done)"
echo "SAN: IP=$IP, 127.0.0.1  DNS=$NAMES"

openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
  -nodes -days 3650 \
  -keyout certs/tracker.key -out certs/tracker.crt \
  -subj "/CN=askr-tracker@$HOST" \
  -addext "subjectAltName=$SAN" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth" 2>/dev/null

chmod 600 certs/tracker.key
echo "できた: $(pwd)/certs/tracker.crt  (有効期限 $(openssl x509 -enddate -noout -in certs/tracker.crt | cut -d= -f2))"
echo "スマホで開く: https://$IP:8443/"
