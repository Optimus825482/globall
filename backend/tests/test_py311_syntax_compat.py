"""Python 3.11 uyum kilidi — üretim imajı 3.11, geliştirme 3.12 (2026-11-12)

CANLI DEPLOY HATASI: `forex_chat.py`'de PEP 701 sözdizimi (iç f-string, dış
tırnağı kullanıyor) 3.12'de geçerliydi ama **3.11 imajında SyntaxError** →
modül import edilemedi → backend açılışta öldü → Coolify "backend unhealthy".

`ast.parse(feature_version=(3,11))` bunu YAKALAMAZ (PEP 701 tokenizer işidir).
Bu yüzden `scripts/check_py311_syntax.py` tokenizer tabanlı dedektör yazıldı ve
aşağıdaki test onu `backend/app` ağacına karşı çalıştırır: bir daha 3.11'i kıran
satır girerse test kırılır (deploy'a gitmeden önce).
"""
from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load_checker():
    path = ROOT / "scripts" / "check_py311_syntax.py"
    spec = importlib.util.spec_from_file_location("check_py311_syntax", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_uygulama_kaynaklari_311_uyumlu():
    checker = _load_checker()
    offenders = []
    for p in (ROOT / "backend" / "app").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        for line, msg in checker.check_file(p):
            offenders.append(f"{p.relative_to(ROOT)}:{line}: {msg}")
    assert not offenders, "3.11 imajında backend'i düşürecek satırlar:\n" + "\n".join(offenders)


def test_dedektor_gercekten_yakaliyor(tmp_path):
    """Dedektörün işe yaradığı kanıtı: bilinen-bozuk örnek ihlal olarak dönmeli."""
    checker = _load_checker()
    bad = tmp_path / "bad.py"
    bad.write_text(
        'd = {"t": 1}\n'
        'x = f"Dolar {\'\' if d is None else f\' · {d.get("t")}\'}"\n',
        encoding="utf-8",
    )
    assert checker.check_file(bad), "dedektör bilinen-bozuk örneği kaçırdı"

    good = tmp_path / "good.py"
    good.write_text('pf = 1.5\nx = f"{(pf if pf else 0):.2f}"\n', encoding="utf-8")
    assert not checker.check_file(good)
