#!/usr/bin/env python3
"""5m replay onbellegini istenen zaman dilimine indirger (M3/M15/M30/H1/H4).

Neden gerekli: forex_replay_backtest.py'de --interval yalnizca Yahoo fetch URL'ini
degistirir; --cache verildiginde hicbir yeniden-ornekleme yapilmaz. Yani
"--interval 15m --cache <5m.json>" cagrisi sessizce 5m barlarla kosar (sahte M15).
Bu script Nx5m bari tek bara indirip ayri bir onbellek dosyasi yazar.
Bar bicimi motorla ayni kalir: [ts, o, h, l, c].

Kullanim:
    python -m scripts.fx_build_tf_cache --tf 15m --src ... --dst ...
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# dakika -> saniye kovasi
TF_MIN = {"3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


def downsample(bars, bucket_sec):
    """Ardisik 5m barlari `bucket_sec` kovalarina indirger: O=ilk, H=max, L=min, C=son."""
    out = []
    cur_key = None
    o = h = l = c = 0.0
    for b in bars:
        key = int(b[0] // bucket_sec) * bucket_sec
        if key != cur_key:
            if cur_key is not None:
                out.append([float(cur_key), o, h, l, c])
            cur_key = key
            o, h, l, c = b[1], b[2], b[3], b[4]
        h = max(h, b[2])
        l = min(l, b[3])
        c = b[4]
    if cur_key is not None:
        out.append([float(cur_key), o, h, l, c])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", required=True, choices=sorted(TF_MIN),
                    help="Hedef zaman dilimi (3m/5m/15m/30m/1h/4h)")
    ap.add_argument("--src", default=os.path.join(ROOT, "outputs", "replay_cache_60d_fxwide.json"))
    ap.add_argument("--dst", default="")
    args = ap.parse_args()

    bucket = TF_MIN[args.tf] * 60
    dst_path = args.dst or os.path.join(ROOT, "outputs", f"replay_cache_60d_fxwide_{args.tf}.json")

    with open(args.src, encoding="utf-8") as f:
        src = json.load(f)

    dst = {sym: downsample(bars, bucket) for sym, bars in src.items()}
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    with open(dst_path, "w", encoding="utf-8") as f:
        json.dump(dst, f)

    for sym in sorted(dst)[:4]:
        b0, b1 = dst[sym][0], dst[sym][-1]
        print(f"{sym:8s} {len(src[sym]):>6} 5m -> {len(dst[sym]):>6} {args.tf}  "
              f"{dt.datetime.fromtimestamp(b0[0], dt.timezone.utc):%Y-%m-%d %H:%M} -> "
              f"{dt.datetime.fromtimestamp(b1[0], dt.timezone.utc):%Y-%m-%d %H:%M}")
    print(f"[OK] {len(dst)} sembol -> {dst_path}")


if __name__ == "__main__":
    main()
