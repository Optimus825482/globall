#!/usr/bin/env python3
"""5m replay onbellegini gercek 15m bara indirger (Asama 3 zaman-dilimi merdiveni).

Neden gerekli: forex_replay_backtest.py'de --interval yalnizca Yahoo fetch URL'ini
degistirir; --cache verildiginde hicbir yeniden-ornekleme yapilmaz. Yani
"--interval 15m --cache <5m.json>" cagrisi sessizce 5m barlarla kosar (sahte M15).
Bu script 3x5m bari tek 15m bara indirip ayri bir onbellek dosyasi yazar.
Bar bicimi motorla ayni kalmali: [ts, o, h, l, c] (5 elemanli).

Kullanim:
    python -m scripts.fx_build_m15_cache \
        --src outputs/replay_cache_60d_fxwide.json \
        --dst outputs/replay_cache_60d_fxwide_m15.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUCKET = 900  # 15 dakika


def to_m15(bars):
    """Ardisik 5m barlari 900s kovalarina indirger: O=ilk, H=max, L=min, C=son."""
    out = []
    cur_key = None
    o = h = l = c = 0.0
    for b in bars:
        key = int(b[0] // BUCKET) * BUCKET
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
    ap.add_argument("--src", default=os.path.join(ROOT, "outputs", "replay_cache_60d_fxwide.json"))
    ap.add_argument("--dst", default=os.path.join(ROOT, "outputs", "replay_cache_60d_fxwide_m15.json"))
    args = ap.parse_args()

    with open(args.src, encoding="utf-8") as f:
        src = json.load(f)

    dst = {sym: to_m15(bars) for sym, bars in src.items()}
    os.makedirs(os.path.dirname(args.dst), exist_ok=True)
    with open(args.dst, "w", encoding="utf-8") as f:
        json.dump(dst, f)

    for sym in sorted(dst)[:4]:
        b0, b1 = dst[sym][0], dst[sym][-1]
        print(f"{sym:8s} {len(src[sym]):>6} 5m -> {len(dst[sym]):>6} 15m  "
              f"{dt.datetime.fromtimestamp(b0[0], dt.timezone.utc):%Y-%m-%d %H:%M} -> "
              f"{dt.datetime.fromtimestamp(b1[0], dt.timezone.utc):%Y-%m-%d %H:%M}")
    print(f"[OK] {len(dst)} sembol -> {args.dst}")


if __name__ == "__main__":
    main()
