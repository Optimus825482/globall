"""DANIŞMAN MODUNDA LLM İNCELEMESİ ARKA PLANDA (2026-11-09).

Neden: danışman modunda LLM kararı işlemi engellemiyordu ama `review_entry` yine
de inline bekleniyordu (ortanca 26 sn, timeout tabanı 40 sn, `_review_lock` yüzünden
adaylar SIRAYLA). Karara etkisi olmayan bir kayıt için girişi bekletmek yanlış
takastı → inceleme arka plana alındı. VETO modunda bekleme ZORUNLU.

Kilitlenen davranış:
  1. `decide(mode="advisory")` **asla** engellemez — LLM çökse (verdict None) bile.
     Aksi hâlde "danışman" diyen ayar LLM kesintisinde tüm işlemleri durdururdu.
  2. `_llm_review_background` karar kaydını yazar, işlem referansını bağlar.
  3. İşlem AÇILMADIYSA "açıldı" işaretlenmez (sahte executed kaydı yok).
  4. Arka plan görevi çökse bile `_LLM_BG_INFLIGHT` temizlenir (kuyruk tıkanmaz).
  5. forex.py: danışman yolu `create_task` kullanır, `await review_entry` YOK;
     veto yolu beklemeye devam eder; referans bağı mark_executed'dan ÖNCE kurulur.
"""
import asyncio
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import llm_trade_review as ltr  # noqa: E402
from app.routers import forex as fx  # noqa: E402

SRC = (ROOT / "app" / "routers" / "forex.py").read_text(encoding="utf-8")


def _v(decision, conf, **kw):
    return {"decision": decision, "confidence": conf, "summary": "s", "reasons": [], "risks": [], **kw}


class TestAdvisoryNeverBlocks(unittest.TestCase):
    def test_error_in_advisory_does_not_block(self):
        r = ltr.decide(None, "timeout", mode="advisory", fail_open=False, min_confidence=55)
        self.assertFalse(r["blocked"], "danışman modu LLM kesintisinde ticareti durdurmamalı")
        self.assertEqual(r["applied"], "advisory_error")

    def test_error_in_veto_follows_fail_open(self):
        self.assertTrue(ltr.decide(None, "timeout", mode="veto", fail_open=False, min_confidence=55)["blocked"])
        self.assertFalse(ltr.decide(None, "timeout", mode="veto", fail_open=True, min_confidence=55)["blocked"])

    def test_reject_in_advisory_does_not_block(self):
        r = ltr.decide(_v("REJECT", 95), None, mode="advisory", fail_open=False, min_confidence=55)
        self.assertFalse(r["blocked"])
        self.assertEqual(r["applied"], "advisory_reject")

    def test_downgraded_in_advisory(self):
        r = ltr.decide(_v("REJECT", 95, downgraded=True), None, mode="advisory", fail_open=False, min_confidence=55)
        self.assertFalse(r["blocked"])

    def test_veto_still_blocks_below_threshold(self):
        r = ltr.decide(_v("APPROVE", 40), None, mode="veto", fail_open=True, min_confidence=55)
        self.assertTrue(r["blocked"])
        self.assertEqual(r["applied"], "blocked")


class TestBackgroundTask(unittest.IsolatedAsyncioTestCase):
    async def _run(self, fake_review, ref):
        calls = {}

        async def _mark(rid, r):
            calls["mark"] = (rid, r)

        orig_r, orig_m = ltr.review_entry, ltr.mark_executed
        ltr.review_entry, ltr.mark_executed = fake_review, _mark
        try:
            fut = asyncio.get_running_loop().create_future()
            if ref is not None:
                fut.set_result(ref)
            else:
                fut.set_exception(RuntimeError("işlem açılmadı"))
            key = ("EURUSD", "BUY")
            fx._LLM_BG_INFLIGHT.add(key)
            await fx._llm_review_background({"symbol": "EURUSD"}, key, fut)
            calls["inflight"] = key in fx._LLM_BG_INFLIGHT
        finally:
            ltr.review_entry, ltr.mark_executed = orig_r, orig_m
            fx._LLM_BG_INFLIGHT.discard(("EURUSD", "BUY"))
        return calls

    async def test_records_and_links_reference(self):
        async def fake(ctx):
            return {"review_id": 77, "blocked": False, "applied": "advisory_reject"}

        calls = await self._run(fake, "CMD-1234")
        self.assertEqual(calls["mark"], (77, "CMD-1234"))
        self.assertFalse(calls["inflight"], "tamamlanınca kuyruğa kayıt bırakmamalı")

    async def test_no_mark_when_trade_not_opened(self):
        async def fake(ctx):
            return {"review_id": 77, "blocked": False}

        calls = await self._run(fake, None)
        self.assertNotIn("mark", calls, "işlem açılmadıysa 'açıldı' işaretlenmemeli")

    async def test_no_mark_when_review_not_saved(self):
        async def fake(ctx):
            return {"review_id": None, "blocked": False}

        calls = await self._run(fake, "CMD-1")
        self.assertNotIn("mark", calls)

    async def test_crash_is_swallowed_and_queue_freed(self):
        async def boom(ctx):
            raise RuntimeError("LLM patladı")

        calls = await self._run(boom, "CMD-1")
        self.assertNotIn("mark", calls)
        self.assertFalse(calls["inflight"], "çökme sonrası kuyruk temizlenmeli")


class TestWiring(unittest.TestCase):
    def _advisory_branch(self):
        i = SRC.index('if str(_AUTO_SETTINGS.llm_review_mode or "veto") == "advisory":')
        j = SRC.index("\n                    else:", i)
        return SRC[i:j]

    def test_advisory_branch_is_backgrounded(self):
        blk = self._advisory_branch()
        self.assertIn("asyncio.create_task(_llm_review_background", blk)
        self.assertNotIn("await llm_trade_review.review_entry", blk,
                         "danışman yolunda async bekleme kalmamalı (26 sn gecikme)")

    def test_veto_branch_still_awaits(self):
        i = SRC.index('if str(_AUTO_SETTINGS.llm_review_mode or "veto") == "advisory":')
        j = SRC.index("\n                    else:", i)
        self.assertIn("await llm_trade_review.review_entry", SRC[j:j + 900],
                      "veto yolunda karar engelleyici: beklemek zorunda")

    def test_reference_settled_before_mark(self):
        i = SRC.index("_ref_fut.set_result(_review_ref)")
        j = SRC.index("await _ltr.mark_executed(_review_id, _review_ref)")
        self.assertLess(i, j)

    def test_inflight_cap_present(self):
        self.assertIn("_LLM_BG_MAX", SRC)
        self.assertIn("len(_LLM_BG_INFLIGHT) < _LLM_BG_MAX", SRC)


if __name__ == "__main__":
    unittest.main()
