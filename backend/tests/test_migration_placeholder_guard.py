"""Migration placeholder-parola koruması (2026-09-27 deploy kazası).

Kaza: Coolify'de ``POSTGRES_PASSWORD_GLOBAL`` tanımlı değilken
``docker-compose.yaml``'daki ``${VAR:?mesaj}`` koruması YERİNDE çalışmadı;
Coolify Bash'ı kendi parser'ıyla değerlendirdi ve hata metnini parola
yerine koydu. Böylece backend şu URL ile açıldı::

    postgresql://scalper:POSTGRES_PASSWORD must be set@postgres_global:5432/…

Bu test, aynı sınıf hatayı (bir sırın yerine hata metnine sessizce düşmesi)
bir daha canlıya çıkmadan yakalar.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_postgres_migration import _reject_placeholder_secrets


class _PlaceholderSecretTests(unittest.TestCase):
    def test_kaza_paylasimi_reddedilir(self):
        # The exact URL from the 2026-09-27 deploy log.
        url = (
            "postgresql://scalper:POSTGRES_PASSWORD must be set"
            "@postgres_global:5432/scalper_global"
        )
        with self.assertRaises(SystemExit) as ctx:
            _reject_placeholder_secrets(url=url)
        # The message must name the variable to set, not just fail.
        self.assertIn("POSTGRES_PASSWORD_GLOBAL", str(ctx.exception))

    def test_placeholder_ailesi_reddedilir(self):
        # Sibling phrasings of the same compose construct; all one bug class.
        for tail in (
            "POSTGRES_PASSWORD is not set",
            "POSTGRES_PASSWORD not defined",
            "LLM_ENCRYPTION_KEY required",
        ):
            with self.subTest(tail=tail):
                url = f"postgresql://scalper:{tail}@postgres_global:5432/scalper_global"
                with self.assertRaises(SystemExit):
                    _reject_placeholder_secrets(url=url)

    def test_gercek_parola_gecer(self):
        # The guard must not be inert. Real random passwords contain no marker.
        for password in ("s3cret-gu3ckenmez", "postgres", "p@ssw0rd!"):
            with self.subTest(password=password):
                url = f"postgresql://scalper:{password}@postgres_global:5432/scalper_global"
                _reject_placeholder_secrets(url=url)  # must NOT raise

    def test_parolasiz_url_gecer(self):
        # No password at all (peer/trust auth) must not trip the guard.
        _reject_placeholder_secrets(url="postgresql://postgres@postgres_global:5432/scalper_global")

    def test_only_password_segment_is_checked(self):
        # Superstring false positive: markers in host / database name must not
        # trip the guard, otherwise a legitimate password blocks startup.
        _reject_placeholder_secrets(url="postgresql://user:pass@required_db_host:5432/testdb")

    def test_bozuk_uri_calismaz(self):
        # Missing "://" or "@" must still raise SystemExit, not IndexError.
        for url in ("", "not a url", "postgresql://"):
            with self.subTest(url=url):
                try:
                    _reject_placeholder_secrets(url=url)
                except SystemExit:
                    pass
                except Exception as exc:
                    self.fail(f"{url!r} beklenmedik hata: {exc!r}")


class _EntrypointContractTests(unittest.TestCase):
    """Korumanın GERÇEKTEN bağlantı öncesi çağrıldığına dair kaynak sözleşmesi.

    Fonksiyonun var olması yetmez: ``main()`` içinden çıkarılırsa koruma
    ölü kod olur ve kaza sessizce tekrarlanır.
    """

    def test_main_her_zaman_once_guarded(self):
        source = (ROOT / "scripts" / "run_postgres_migration.py").read_text(encoding="utf-8")
        body = source.split("async def main()", 1)[1]
        guard_at = body.index("_reject_placeholder_secrets(url)")
        connect_at = body.index("asyncpg.connect")
        self.assertLess(guard_at, connect_at, "kontrol bağlantıdan SONRA kalmış")
        # ve DATABASE_URL boşluğundan hemen sonra, arada başka iş yok
        self.assertIn('raise SystemExit("DATABASE_URL gerekli")', body)


if __name__ == "__main__":
    unittest.main()
