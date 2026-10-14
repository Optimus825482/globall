#!/usr/bin/env bash
# Squeeze-KC canlı-parite A/B: kolun defteri düşürüp düşürmediğini canlının GERÇEK
# bayraklarıyla ölçer (st-filter + ST muafiyeti, major-min-atr 2.5, max-open 99,
# chandelier 0.3, max-spread 10.0). İki pencere (OOS/IS) × iki spread (1×/2×) × iki
# kol (base = squeeze_kc kapalı, trt = açık). Sonuç: outputs/skc_ab_*.json
#
# Kullanım: bash scripts/_run_skc_ab.sh      (venv python; ~2 dk/koşum, 8 koşum)
set -u
cd "$(dirname "$0")/.." || exit 1
PY=./backend/venv/Scripts/python.exe
CACHE=outputs/replay_cache_db_15m.json
ARMS_COMMON="s3_5m=XAUUSD;s3_15m=XAUUSD,BTCUSD,US30,GBPUSD;ema_adx_pullback=XAUUSD,NAS100;london_breakout=XAUUSD,GBPUSD,USDJPY,BTCUSD,USDCHF,US30;donchian_adx=XAUUSD,GBPJPY,EURJPY,NAS100"
ARMS_TRT="$ARMS_COMMON;squeeze_kc=XAUUSD,BTCUSD,US30,NAS100,USDCHF"
LIVE_FLAGS="--skip-old --max-open 99 --max-spread 10.0 --major-min-atr 2.5 --st-filter --st-exempt-arms --chandelier 0.3"

run() {  # $1=etiket $2=arm $3=spread-profili $4=start $5=end
  echo ">>> $1  ($4 -> $5)"
  PYTHONUTF8=1 $PY scripts/forex_replay_backtest.py \
    --cache "$CACHE" --spread-profile "$3" --combined --arm-symbols "$2" \
    $LIVE_FLAGS --start "$4" --end "$5" --tag "$1" --out "outputs/skc_ab_$1.json" \
    > "outputs/skc_ab_$1.log" 2>&1
  echo "    bitti: $1 (cikis $?)"
}

for SPREAD_TAG in x1 x2; do
  if [ "$SPREAD_TAG" = "x1" ]; then SP=outputs/fx_spread_db_15m.json; else SP=outputs/fx_spread_db_15m_x2.json; fi
  run "oos_${SPREAD_TAG}_base" "$ARMS_COMMON" "$SP" 2026-09-07 2026-10-07
  run "oos_${SPREAD_TAG}_trt"  "$ARMS_TRT"    "$SP" 2026-09-07 2026-10-07
  run "is_${SPREAD_TAG}_base"  "$ARMS_COMMON" "$SP" 2026-08-01 2026-09-07
  run "is_${SPREAD_TAG}_trt"   "$ARMS_TRT"    "$SP" 2026-08-01 2026-09-07
done
echo "=== TUM KOSUMLAR BITTI ==="
