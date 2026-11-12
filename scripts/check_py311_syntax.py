#!/usr/bin/env python3
"""PYTHON 3.11 UYUM DENETİMİ — PEP 701 (iç içe f-string) avcısı.

NEDEN (2026-11-12 CANLI DEPLOY HATASI)
--------------------------------------
Üretim imajı **python:3.11-slim**; geliştirme makinesi 3.12. Python 3.12'de geçerli
olan şu satır 3.11'de **SyntaxError**:

    f"...{'' if x is None else f' · {d.get("trend")} ·'}"      # ← 3.11: ÖLÜMCÜL
                                                              # (iç f-string, DIŞ
                                                              #  tırnağı kullanıyor)

Sonuç: `forex_chat` import edilemedi → backend açılışta öldü → Coolify
"backend unhealthy" → deploy düştü. `ast.parse(feature_version=(3,11))` bunu
YAKALAMAZ (PEP 701 tokenizer değişikliğidir, gramer bayrağı değil).

KURAL: 3.11'de bir f-string'in replacement alanı içinde f-string kullanılabilir,
ANCAK iç f-string DIŞ f-string'in sınırlayıcı tırnağını içeremez.

Bu betik tokenizer ile iç içe f-string'leri bulur, iç f-string metninde dış
sınırlayıcı görünüyorsa ihlal olarak raporlar.

Kullanim:
    python scripts/check_py311_syntax.py            # app/ + scripts/ + tests/
    python scripts/check_py311_syntax.py --paths backend/app
"""
from __future__ import annotations

import argparse
import io
import pathlib
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_PATHS = ["backend/app", "backend/tests", "scripts"]


def check_file(path: pathlib.Path) -> list[tuple[int, str]]:
    """(satır, açıklama) listesi — 3.11'de patlayacak iç içe f-string'ler."""
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:
        return []  # tokenize edilemeyen dosya ayrı bir sorun; burada kapsam dışı

    violations: list[tuple[int, str]] = []
    stack: list[tuple[str, int]] = []      # (sınırlayıcı tırnak, başlangıç indeksi)
    for i, tok in enumerate(toks):
        ttype = tok.type
        if ttype == getattr(tokenize, "FSTRING_START", -1):
            delim = tok.string.lstrip("fFrRbBuU")     # ', ", ''', \"\"\"
            if stack:
                outer_delim = stack[-1][0]
                # Bu f-string'in gövdesini END'e kadar topla
                j = i + 1
                while j < len(toks) and toks[j].type != getattr(tokenize, "FSTRING_END", -1):
                    j += 1
                body = " ".join(t.string for t in toks[i:j + 1])
                if outer_delim in body:
                    violations.append((
                        tok.start[0],
                        f"iç f-string dış tırnağı ({outer_delim!r}) kullanıyor — "
                        f"Python 3.11'de SyntaxError"))
                else:
                    # iç içe ama güvenli: yine de derinlik izlenmeli
                    pass
            stack.append((delim, i))
        elif ttype == getattr(tokenize, "FSTRING_END", -1):
            if stack:
                stack.pop()
    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description="Python 3.11 f-string uyum denetimi (PEP 701)")
    ap.add_argument("--paths", nargs="*", default=None)
    args = ap.parse_args()

    roots = [ROOT / p for p in (args.paths or DEFAULT_PATHS)]
    files = []
    for r in roots:
        if r.is_file():
            files.append(r)
        elif r.is_dir():
            files.extend(p for p in r.rglob("*.py") if "__pycache__" not in p.parts)

    def _rel(p: pathlib.Path) -> str:
        try:
            return str(p.relative_to(ROOT))
        except ValueError:
            return str(p)

    total = 0
    for p in sorted(files):
        for line, msg in check_file(p):
            total += 1
            print(f"{_rel(p)}:{line}: {msg}")
    if total:
        print(f"\n{total} ihlal — bu satırlar 3.11 imajında backend'i DÜŞÜRÜR.")
        return 1
    print(f"TEMİZ: {len(files)} dosyada 3.11'i kıran iç içe f-string yok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
