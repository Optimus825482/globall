import json

import pytest
from app.forex_news import get_forex_news, FALLBACK_EVENTS, FALLBACK_NEWS, translate_title, map_symbols_for_event, generate_event_scenario


import asyncio

def test_get_forex_news_structure():
    events = asyncio.run(get_forex_news(force_refresh=False))
    assert isinstance(events, list)
    assert len(events) > 0

    first = events[0]
    assert "id" in first
    assert "title" in first
    assert "country" in first
    assert "stars" in first
    assert first["stars"] in [2, 3]
    assert "impact" in first
    assert first["impact"] in ["High", "Medium"]
    assert "scenario" in first
    assert "bullish_trigger" in first["scenario"]
    assert "bullish_outcome" in first["scenario"]
    assert "bearish_trigger" in first["scenario"]
    assert "bearish_outcome" in first["scenario"]
    assert "summary_short" in first["scenario"]
    assert "affected_symbols" in first
    assert len(first["affected_symbols"]) > 0


def test_symbol_mapping():
    usd_syms = map_symbols_for_event("USD", "Consumer Price Index")
    assert "XAUUSD" in usd_syms
    assert "EURUSD" in usd_syms

    oil_syms = map_symbols_for_event("USD", "EIA Crude Oil Stocks")
    assert "USOIL" in oil_syms


def test_fallback_news_alias():
    assert FALLBACK_NEWS is FALLBACK_EVENTS
    assert len(FALLBACK_EVENTS) >= 5
    for ev in FALLBACK_EVENTS:
        assert ev["stars"] in [2, 3]
        assert len(ev["affected_symbols"]) > 0


def test_turkish_comment_resolution():
    from app.forex_news import get_turkish_comment
    # Trade balance
    c1 = get_turkish_comment("", "Trade Balance", "Almanya Dış Ticaret Dengesi")
    assert "Dış Ticaret Dengesi" in c1
    # CPI
    c2 = get_turkish_comment("", "Consumer Price Index", "TÜFE Enflasyon")
    assert "Tüketici Fiyat Endeksi" in c2
    # Generic
    c3 = get_turkish_comment("", "Some Unknown Event", "Bilinmeyen Gösterge")
    assert "piyasa katılımcıları" in c3


def test_economic_calendar_db_persistence():
    from app import database
    from app.forex_news import sync_economic_calendar_to_db, _CALENDAR_CACHE

    # Test event saving and loading
    sample_events = [
        {
            "id": "test-cal-1",
            "title": "Fed Faiz Kararı Test",
            "original_title": "Fed Interest Rate Test",
            "country": "USD",
            "currency": "USD",
            "country_name": "ABD",
            "flag": "🇺🇸",
            "date_str": "Bugün 21:00",
            "date_iso": "2026-10-08T18:00:00Z",
            "impact": "High",
            "stars": 3,
            "stars_str": "⭐⭐⭐",
            "impact_label": "⭐⭐⭐ YÜKSEK (3 Yıldız)",
            "forecast": "5.00%",
            "previous": "5.25%",
            "actual": "—",
            "status": "Bekleniyor",
            "affected_symbols": ["XAUUSD", "EURUSD"],
            "scenario": {
                "title": "Test Senaryo",
                "bullish_trigger": "Faiz Sabit",
                "bullish_outcome": "Dolar Artar",
                "bearish_trigger": "Faiz İndirimi",
                "bearish_outcome": "Dolar Düşer",
                "summary_short": "Test Özet",
            },
        }
    ]

    # Test DB save
    count = asyncio.run(database.save_economic_calendar_events(sample_events))
    assert count == 1

    # Test DB read
    loaded = asyncio.run(database.get_economic_calendar_events())
    assert len(loaded) >= 1
    found = next((x for x in loaded if x.get("id") == "test-cal-1"), None)
    assert found is not None
    assert found["title"] == "Fed Faiz Kararı Test"
    assert found["stars"] == 3

    # Test last sync ts
    last_sync = asyncio.run(database.get_last_economic_calendar_sync())
    assert last_sync > 0

    # Test get_forex_news reads from cache / DB without network delay
    _CALENDAR_CACHE["items"] = []
    _CALENDAR_CACHE["timestamp"] = 0
    news = asyncio.run(get_forex_news(force_refresh=False))
    assert isinstance(news, list)
    assert len(news) > 0
    assert any(x.get("id") == "test-cal-1" for x in news)


# ============================================================================
# AÇIKLANAN VERİ KIYASI — "HANGİ SENARYO GERÇEKLEŞTİ?"
# ============================================================================

def test_parse_calendar_value_formats():
    from app.forex_news import parse_calendar_value

    # Yüzde: işaret atılır, 100'e BÖLÜNMEZ (actual ile forecast aynı birimde kıyaslanır).
    assert parse_calendar_value("0.2%") == pytest.approx(0.2)
    assert parse_calendar_value("3.50%") == pytest.approx(3.5)
    # Çarpan ekleri.
    assert parse_calendar_value("145K") == pytest.approx(145_000)
    assert parse_calendar_value("-1.5M") == pytest.approx(-1_500_000)
    assert parse_calendar_value("2.1B") == pytest.approx(2.1e9)
    # Ondalık virgül (nokta yokken).
    assert parse_calendar_value("2,2%") == pytest.approx(2.2)
    # Binlik ayraç olarak virgül.
    assert parse_calendar_value("1,234") == pytest.approx(1234)
    assert parse_calendar_value("1,234.5") == pytest.approx(1234.5)
    # Ham sayılar.
    assert parse_calendar_value(-4.2) == pytest.approx(-4.2)
    assert parse_calendar_value("148.2") == pytest.approx(148.2)
    # Veri yok / ayrıştırılamaz.
    for missing in ["—", "", "  ", "N/A", "n/a", "null", None, "abc", "—%"]:
        assert parse_calendar_value(missing) is None, missing


def test_outcome_standard_rule_higher_is_bullish():
    from app.forex_news import evaluate_event_outcome

    # Faiz: beklenti üstü = şahin = 🟢
    rate = evaluate_event_outcome("Fed Interest Rate Decision", "5.00%", "5.25%", "5.25%")
    assert rate["side"] == "bullish"
    assert rate["basis"] == "forecast"
    assert rate["bucket"] == "rate"
    assert rate["label_tr"] == "Beklenti Üzeri"

    # GSYH: yüksek = 🟢
    gdp = evaluate_event_outcome("GDP Growth", "2.0%", "1.8%", "2.5%")
    assert gdp["side"] == "bullish"
    assert gdp["bucket"] == "gdp"

    # PMI: yüksek = 🟢
    pmi = evaluate_event_outcome("ISM Manufacturing PMI", "49.0", "48.0", "51.0")
    assert pmi["side"] == "bullish"

    # Genel: yüksek = 🟢
    generic = evaluate_event_outcome("Some Unknown Indicator", "10", "9", "12")
    assert generic["side"] == "bullish"


def test_outcome_inflation_family_is_not_inverted():
    """Enflasyon ailesi TERS ÇEVRİLMEZ: yüksek enflasyon şahindir ve senaryonun
    `bullish_trigger` metni zaten 'Enflasyon Beklenti Üstü (Sıcak Veri)' der."""
    from app.forex_news import evaluate_event_outcome

    hot = evaluate_event_outcome("CPI YoY", "3.0%", "3.1%", "3.2%")
    assert hot["side"] == "bullish"
    assert hot["bucket"] == "inflation"

    cold = evaluate_event_outcome("CPI YoY", "3.0%", "3.1%", "2.8%")
    assert cold["side"] == "bearish"
    assert cold["label_tr"] == "Beklenti Altı"


def test_outcome_employment_inversion():
    """İstihdam artışı 🟢; işsizlik/başvuru artışı 🔴 (aynı kovada ters yön)."""
    from app.forex_news import evaluate_event_outcome

    nfp = evaluate_event_outcome("Non-Farm Payrolls", "180K", "170K", "200K")
    assert nfp["side"] == "bullish"
    assert nfp["bucket"] == "employment"

    # NOT: "Unemployment Rate" kovada `rate`'e düşer (mevcut `generate_event_scenario`
    # `rate` anahtar kelimesini önce kontrol ediyor). Yön kuralı yine doğrudur, çünkü
    # işsizlik ters çevirmesi KOVA kontrolünden ÖNCE uygulanır — bu ayrım kasıtlıdır.
    unemployment = evaluate_event_outcome("Unemployment Rate", "4.2%", "4.1%", "4.5%")
    assert unemployment["side"] == "bearish"

    claims = evaluate_event_outcome("Initial Jobless Claims", "230K", "225K", "250K")
    assert claims["side"] == "bearish"


def test_outcome_oil_stocks_inversion():
    """Stok artışı arz bolluğudur → 🔴; stok düşüşü → 🟢."""
    from app.forex_news import evaluate_event_outcome

    build = evaluate_event_outcome("EIA Crude Oil Inventories", "+0.5M", "+0.2M", "+2.1M")
    assert build["side"] == "bearish"
    assert build["bucket"] == "oil_stocks"

    draw = evaluate_event_outcome("EIA Crude Oil Inventories", "+0.5M", "+1.0M", "-1.5M")
    assert draw["side"] == "bullish"


def test_outcome_basis_prefers_forecast_then_previous():
    """Canlı akışta olayların çoğunda `forecast` BOŞ, `previous` doludur — bu yüzden
    `previous` tabanı ana yoldur ve rozet metni tabana göre değişmek zorundadır."""
    from app.forex_news import evaluate_event_outcome

    # forecast dolu -> forecast tabanı
    with_forecast = evaluate_event_outcome("Retail Sales", "0.3%", "0.1%", "0.5%")
    assert with_forecast["basis"] == "forecast"
    assert with_forecast["label_tr"] == "Beklenti Üzeri"

    # forecast boş -> previous tabanı, ama sonuç YİNE hesaplanır
    no_forecast = evaluate_event_outcome("MBA Mortgage Applications", None, "-6%", "-4.2%")
    assert no_forecast is not None
    assert no_forecast["basis"] == "previous"
    assert no_forecast["side"] == "bullish"
    assert no_forecast["label_tr"] == "Önceki'ye Göre Artış"

    no_forecast_down = evaluate_event_outcome("MBA Purchase Index", "—", "148.2", "145.1")
    assert no_forecast_down["side"] == "bearish"
    assert no_forecast_down["label_tr"] == "Önceki'ye Göre Azalış"
    assert "Önceki'ye Göre Azalış" in no_forecast_down["comparison_tr"]


def test_outcome_undecidable_returns_none():
    from app.forex_news import evaluate_event_outcome

    # actual yok -> karar verilemez (asla tahmin edilmez)
    assert evaluate_event_outcome("CPI YoY", "3.0%", "2.9%", "—") is None
    # HER İKİ taban da yok -> karar verilemez
    assert evaluate_event_outcome("CPI YoY", "—", "—", "3.2%") is None
    # Ayrıştırılamayan actual
    assert evaluate_event_outcome("CPI YoY", "3.0%", "2.9%", "abc") is None
    # Eşitlik -> side None (dal gizlenmez, ikisi de gösterilir)
    tie = evaluate_event_outcome("CPI YoY", "3.0%", "2.9%", "3.0%")
    assert tie is not None
    assert tie["side"] is None
    assert tie["label_tr"] == "Beklentiye Uygun"


def test_outcome_comparison_text_keeps_source_units():
    """Kıyas metni HAM kaynak metni kullanmalı — sayıyı yeniden basmak çift birim
    üretir (`145K` -> 145000.0 -> "145000K") ve `:g` ile üstel gösterime düşer
    (`2.4M` -> 2400000.0 -> "2.4e+06M"). İkisi de operatörün okuduğu satırdır."""
    from app.forex_news import evaluate_event_outcome

    k = evaluate_event_outcome("US Unemployment Claims", "220K", "215K", "231K")
    assert k["comparison_tr"] == "231K > 220K (Beklenti Üzeri)"

    m = evaluate_event_outcome("EIA Crude Oil Inventories", "-1.2M", "-0.8M", "2.4M")
    assert m["comparison_tr"] == "2.4M > -1.2M (Beklenti Üzeri)"

    pct = evaluate_event_outcome("US CPI YoY", "3.0%", "2.9%", "3.2%")
    assert pct["comparison_tr"] == "3.2% > 3.0% (Beklenti Üzeri)"

    # previous tabanında da taban metni previous'ın kendi birimini taşır.
    prev = evaluate_event_outcome("MBA Purchase Index", "—", "148.2", "145.1")
    assert prev["comparison_tr"] == "145.1 < 148.2 (Önceki'ye Göre Azalış)"


def test_outcome_inversion_carries_direction_note():
    """Ters ailelerde sayısal ilişki ile piyasa yönü ayrışır. Rozet "Beklenti Üzeri"
    derken dal 🔴 olur — arayüz bunu açıklayabilmeli, yoksa özelliğin önlemek için
    var olduğu yanlış okuma bizzat üretilir."""
    from app.forex_news import evaluate_event_outcome

    claims = evaluate_event_outcome("Initial Jobless Claims", "230K", "225K", "250K")
    assert claims["side"] == "bearish"
    assert claims["label_tr"] == "Beklenti Üzeri"
    assert claims["direction_note_tr"]

    oil = evaluate_event_outcome("EIA Crude Oil Inventories", "+0.5M", "+0.2M", "+2.1M")
    assert oil["direction_note_tr"]

    # Ters OLMAYAN ailelerde not boş kalır — gereksiz uyarı basılmaz.
    assert evaluate_event_outcome("CPI YoY", "3.0%", "2.9%", "3.2%")["direction_note_tr"] is None
    assert evaluate_event_outcome("Non-Farm Payrolls", "180K", "170K", "200K")["direction_note_tr"] is None

    # Eşitlikte yön yoktur -> açıklanacak bir ayrışma da yoktur.
    tie = evaluate_event_outcome("Initial Jobless Claims", "230K", "225K", "230K")
    assert tie["side"] is None
    assert tie["direction_note_tr"] is None


def test_classify_bucket_order_and_oil_narrowing():
    """Kova sırası korunur ('Fed ... Inflation' -> rate) ve 'Business Inventories'
    petrol dışı olduğu için ters çevrilmez."""
    from app.forex_news import classify_event_bucket, higher_is_bullish_for_event

    assert classify_event_bucket("Fed Inflation Statement") == "rate"
    assert classify_event_bucket("CPI YoY") == "inflation"
    assert classify_event_bucket("EIA Crude Oil Inventories") == "oil_stocks"
    assert classify_event_bucket("Totally Unknown Thing") == "generic"

    # Petrol dışı stok başlığı stok kovasına düşse bile yönü ters çevrilmez.
    assert higher_is_bullish_for_event("Business Inventories") is True
    assert higher_is_bullish_for_event("EIA Crude Oil Inventories") is False
    assert higher_is_bullish_for_event("Unemployment Rate") is False


def test_business_inventories_is_no_longer_oil_bucket():
    """`inventories`/`stok` çıplak anahtar kelimesi kovadan ÇIKARILDI.

    Eskiden "Business Inventories" ham petrol kovasına düşüyordu ve senaryo metni
    ona "Ham Petrol Stok Senaryosu" diyordu — petrolle ilgisi olmayan bir olay için
    yanlış yorum. Artık `generic`'e düşer.
    """
    from app.forex_news import classify_event_bucket, is_oil_stock_event

    assert classify_event_bucket("Business Inventories") == "generic"
    assert is_oil_stock_event("Business Inventories") is False

    scenario = generate_event_scenario("Business Inventories", "ABD", "USD", ["XAUUSD"])
    assert "Ham Petrol" not in scenario["title"]

    # Gerçek petrol olayları kovada ve ters çevrilmiş kalır.
    assert classify_event_bucket("EIA Crude Oil Inventories") == "oil_stocks"
    assert is_oil_stock_event("EIA Crude Oil Inventories") is True
    assert is_oil_stock_event("USOIL Petrol Stokları") is True


def test_eia_gas_storage_is_not_oil_bucket():
    """`eia` bilerek petrol belirtecinden çıkarıldı: "EIA Natural Gas Storage"
    içinde petrol kelimesi GEÇMEZ, `eia` belirteç olsaydı o olay yanlışlıkla ham
    petrol senaryosuna düşerdi."""
    from app.forex_news import classify_event_bucket, higher_is_bullish_for_event, is_oil_stock_event

    assert is_oil_stock_event("EIA Natural Gas Storage") is False
    assert classify_event_bucket("EIA Natural Gas Storage") == "generic"
    # Ters çevrilmez: doğal gaz depolama artışı ham petrol yön kuralını almaz.
    assert higher_is_bullish_for_event("EIA Natural Gas Storage") is True


def test_bucket_and_direction_cannot_diverge():
    """YAPISAL garanti: kova `is_oil_stock_event` ile TANIMLANDIĞI için
    'hangi kovada' ile 'yön nasıl çevrilir' ayrışamaz."""
    from app.forex_news import classify_event_bucket, higher_is_bullish_for_event

    titles = [
        "EIA Crude Oil Inventories", "USOIL Petrol Stokları", "Business Inventories",
        "EIA Natural Gas Storage", "Unemployment Rate", "CPI YoY", "Totally Unknown",
    ]
    for t in titles:
        in_oil_bucket = classify_event_bucket(t) == "oil_stocks"
        inverted = higher_is_bullish_for_event(t) is False
        # Petrol kovasındaki her olay ters, petrol kovası dışındaki hiçbir olay
        # YALNIZ petrol nedeniyle ters değil (işsizlik ailesi ayrı bir gerekçedir).
        if in_oil_bucket:
            assert inverted, t


# ============================================================================
# BİRİM UYUMLULUK KAPISI — "%" ile "K" körlemesine kıyaslanmaz
# ============================================================================

def test_calendar_value_unit_family():
    from app.forex_news import calendar_value_unit_family

    assert calendar_value_unit_family("3.0%") == "percent"
    assert calendar_value_unit_family("-1.5M") == "count"
    assert calendar_value_unit_family("145K") == "count"
    assert calendar_value_unit_family("19.5€") == "currency"
    assert calendar_value_unit_family("60.33$") == "currency"
    assert calendar_value_unit_family("148.2") == "index"

    # Bilinmiyor: veri yok ya da tanınmayan harf taşıyor.
    assert calendar_value_unit_family("—") is None
    assert calendar_value_unit_family(None) is None
    assert calendar_value_unit_family("85cf") is None


def test_units_compatible_gate():
    from app.forex_news import units_compatible

    # Aynı aile -> geçerli.
    assert units_compatible("3.2%", "3.0%") is True
    assert units_compatible("145K", "-1.5M") is True

    # Farklı aile -> kıyas REDDEDİLİR (hedef hata).
    assert units_compatible("3.0%", "145K") is False
    assert units_compatible("2.5%", "19.5€") is False

    # Bilinmezlik engellemez.
    assert units_compatible("—", "3.2%") is True

    # `index` jokerdir: TradingView'in `unit` alanı güvenilmez (canlı probda `€`
    # bozuk karakter geldi), joker olmasaydı gerçek TV satırları haksız yere düşerdi.
    assert units_compatible("148.2", "3.2%") is True
    assert units_compatible("0.3", "0.2%") is True


def test_outcome_rejects_unit_mismatch():
    from app.forex_news import evaluate_event_outcome

    # "%" beklentiye "K" açıklanan: sayısal kıyas 3.0 < 145000 verirdi ve olay
    # KESİN bir yön kazanırdı; doğru cevap "bilinmiyor"dur.
    assert evaluate_event_outcome("CPI YoY", "3.0%", "2.9%", "145K") is None

    # Aynı ailede kıyas yine çalışır — kapı aşırı geniş değil.
    ok = evaluate_event_outcome("CPI YoY", "3.0%", "2.9%", "3.2%")
    assert ok is not None and ok["side"] == "bullish"


def test_outcome_unit_rejection_keeps_has_data_true():
    """Reddin kullanıcıya görünen sonucu: `outcome=None` ama `has_data=True`.
    Olay vitrine GİRMEZ, modalda iki dal + 'ayrıştırılamadı' mesajı görünür."""
    from app.forex_news import _update_event_dynamic_fields

    ev = {
        "id": "unit-mismatch-1",
        "title": "ABD TÜFE",
        "original_title": "CPI YoY",
        "date_iso": "2026-10-10T12:30:00Z",
        "forecast": "3.0%",
        "previous": "2.9%",
        "actual": "145K",
    }
    _update_event_dynamic_fields([ev])
    assert ev["has_data"] is True
    assert ev["outcome"] is None
    # Veri var olduğu için durum "Açıklandı" kalır — değerler görünür, yön yok.
    assert ev["status"] == "Açıklandı"


# ============================================================================
# KAYNAK BİRLEŞTİRME — TradingView (kapsam) + Investing (değer)
# ============================================================================

def test_normalize_event_title_strips_qualifiers():
    from app.forex_news import normalize_event_title

    assert normalize_event_title("CB Consumer Confidence Prel") == "cb consumer confidence"
    assert normalize_event_title("CB Consumer Confidence") == "cb consumer confidence"
    assert normalize_event_title("  Manufacturing   PMI  Flash ") == "manufacturing pmi"
    assert normalize_event_title("CPI Final") == "cpi"

    # Yalnız SONDAKİ belirteç atılır. Baştaki/ortadaki kelime ATILMAZ: "Final CPI"
    # ile "CPI" farklı dizelere düşer ve eşleşmez (kopya satır — kabul edilen bedel).
    # Baştan da atsaydık "Advanced Retail Sales" gibi başlıklar beklenmedik biçimde
    # birleşebilirdi; yanlış birleştirme, kopya satırdan daha kötüdür.
    assert normalize_event_title("Final CPI") == "final cpi"
    assert normalize_event_title("Flash Manufacturing PMI") == "flash manufacturing pmi"

    # Aksan duyarsız: birleşen işaretler atılır, harfin kendisi kalır.
    # (NFKC kullanılsaydı Türkçe `İ` birleşen nokta bırakır, `\w` sınıfına
    # girmeyen o işaret ayraç sanılıp boşluğa çevrilir ve "i şsizlik" gibi bozuk
    # bir anahtar üretilirdi — sessiz eşleşme kaybı.)
    assert normalize_event_title("İşsizlik") == "issizlik"
    assert normalize_event_title("Café PMI") == "cafe pmi"
    # Kısmi ayrışma: `ş` (U+015F) -> `s` + birleşen sedil, sedil atılır -> `s`;
    # ama `ı` (U+0131) ayrışmayan AYRI bir harftir, korunur. Kod noktalarıyla
    # yazıldı — kaynak dosyanın kodlamasından bağımsız kesin olsun.
    assert normalize_event_title("Dış Ticaret Dengesi") == "dıs ticaret dengesi"

    # SINIR — Türkçe `ı` (noktasız i) bir aksan değil, AYRI bir harftir ve
    # korunur; bu yüzden "Oranı" != "Orani". Eşleştirme pratikte İngilizce
    # `original_title` üzerinden yapıldığı için bu kayıp gerçekleşmez; not
    # burada, çünkü davranış bilinçli olsun.
    assert normalize_event_title("Oranı") == "oranı"

    # Boş girdi.
    assert normalize_event_title("") == ""
    assert normalize_event_title(None) == ""


def test_event_minute_parsing():
    from app.forex_news import _event_minute

    assert _event_minute("2026-10-10T12:30:00Z") == _event_minute("2026-10-10T12:30:00+00:00")
    assert _event_minute("2026-10-10T12:30:45Z") == _event_minute("2026-10-10T12:30:00Z")

    # Ayrıştırılamaz ya da eksik -> None (indekslenemez -> güvenli taraf).
    assert _event_minute(None) is None
    assert _event_minute("") is None
    assert _event_minute("bugün") is None


def _tv_event(ev_id, title, currency, date_iso, **values):
    ev = {
        "id": ev_id,
        "title": f"TR {title}",
        "original_title": title,
        "currency": currency,
        "country": currency,
        "country_name": "Test",
        "stars": 3,
        "date_iso": date_iso,
        "forecast": "—",
        "previous": "—",
        "actual": "—",
        "scenario": {"title": "Test Senaryo"},
    }
    ev.update(values)
    return ev


def _inv_event(ev_id, title, currency, date_iso, **values):
    ev = _tv_event(ev_id, title, currency, date_iso, **values)
    ev.pop("scenario", None)
    ev["source"] = "investing"
    return ev


def test_merge_single_candidate_takes_investing_triple():
    """Tam 1 aday -> Investing üçlüsü kazanır, TradingView kimlik/kapsam alanları korunur."""
    from app.forex_news import merge_calendar_sources

    tv = [_tv_event("cal-tv-1", "CB Consumer Confidence", "USD", "2026-10-10T14:00:00Z",
                    previous="97.4", stars=3)]
    inv = [_inv_event("cal-inv-1", "CB Consumer Confidence Prel", "USD", "2026-10-10T14:00:00Z",
                      forecast="98.0", previous="97.4", actual="99.2")]

    merged = merge_calendar_sources(tv, inv)
    assert len(merged) == 1
    row = merged[0]
    assert (row["forecast"], row["previous"], row["actual"]) == ("98.0", "97.4", "99.2")
    # Kimlik ve kapsam TradingView'den.
    assert row["id"] == "cal-tv-1"
    assert row["scenario"] == {"title": "Test Senaryo"}
    assert row["stars"] == 3
    assert row["source"] == "investing"
    assert row["matched_source_id"] == "cal-inv-1"


def test_merge_unmatched_overlay_is_appended():
    from app.forex_news import merge_calendar_sources

    tv = [_tv_event("cal-tv-1", "CPI YoY", "USD", "2026-10-10T12:30:00Z")]
    inv = [_inv_event("cal-inv-9", "German Industrial Production", "EUR", "2026-10-10T06:00:00Z",
                      actual="1.2%")]

    merged = merge_calendar_sources(tv, inv)
    assert len(merged) == 2
    assert merged[1]["id"] == "cal-inv-9"
    assert merged[1]["actual"] == "1.2%"


def test_merge_ambiguous_key_does_not_merge():
    """Aynı para birimi + dakika YETMEZ: CAD'de 12:30'da hem 'Unemployment Rate'
    hem 'Employment Change' var. Farklı başlık -> eşleşme yok -> kopya satır."""
    from app.forex_news import merge_calendar_sources

    tv = [
        _tv_event("cal-tv-1", "Unemployment Rate", "CAD", "2026-10-10T12:30:00Z"),
        _tv_event("cal-tv-2", "Employment Change", "CAD", "2026-10-10T12:30:00Z"),
    ]
    inv = [_inv_event("cal-inv-1", "Unemployment Rate", "CAD", "2026-10-10T12:30:00Z",
                      forecast="7.1%", actual="7.2%")]

    merged = merge_calendar_sources(tv, inv)
    assert len(merged) == 2  # birleşti, üçüncü satır yok
    assert merged[0]["actual"] == "7.2%"

    # Aynı başlıktan İKİ TradingView satırı varsa belirsizlik oluşur -> birleştirme yok.
    dup_tv = [
        _tv_event("cal-tv-a", "Unemployment Rate", "CAD", "2026-10-10T12:30:00Z"),
        _tv_event("cal-tv-b", "Unemployment Rate", "CAD", "2026-10-10T12:30:00Z"),
    ]
    merged_dup = merge_calendar_sources(dup_tv, inv)
    assert len(merged_dup) == 3
    assert merged_dup[2]["id"] == "cal-inv-1"


def test_merge_consumed_candidate_produces_copy():
    """İki Investing olayı aynı anahtara düşerse ikincisi birleşmez (aday tüketilmiş)
    — yanlış birleştirme yerine görünür kopya."""
    from app.forex_news import merge_calendar_sources

    tv = [_tv_event("cal-tv-1", "CPI YoY", "USD", "2026-10-10T12:30:00Z")]
    inv = [
        _inv_event("cal-inv-1", "CPI YoY", "USD", "2026-10-10T12:30:00Z", actual="3.2%"),
        _inv_event("cal-inv-2", "CPI YoY", "USD", "2026-10-10T12:30:00Z", actual="3.3%"),
    ]

    merged = merge_calendar_sources(tv, inv)
    assert len(merged) == 2
    assert merged[0]["actual"] == "3.2%"
    assert merged[1]["id"] == "cal-inv-2"


def test_merge_does_not_mutate_inputs():
    from app.forex_news import merge_calendar_sources

    tv = [_tv_event("cal-tv-1", "CPI YoY", "USD", "2026-10-10T12:30:00Z", actual="—")]
    inv = [_inv_event("cal-inv-1", "CPI YoY", "USD", "2026-10-10T12:30:00Z", actual="3.2%")]

    merge_calendar_sources(tv, inv)
    assert tv[0]["actual"] == "—"
    assert "source" not in tv[0]


def test_merge_unindexable_overlay_is_appended():
    """Ayrıştırılamayan `date_iso` ya da boş para birimi indekslenemez -> 0 eşleşme -> eklenir."""
    from app.forex_news import merge_calendar_sources

    tv = [_tv_event("cal-tv-1", "CPI YoY", "USD", "2026-10-10T12:30:00Z")]
    inv = [
        _inv_event("cal-inv-1", "CPI YoY", "USD", "bugün", actual="3.2%"),
        _inv_event("cal-inv-2", "CPI YoY", "", "2026-10-10T12:30:00Z", actual="3.3%"),
    ]

    merged = merge_calendar_sources(tv, inv)
    assert len(merged) == 3
    assert merged[0]["actual"] == "—"


# ============================================================================
# INVESTING AYRIŞTIRICI (saf, ağsız)
# ============================================================================

def test_parse_investing_payload_extracts_mid_high_events():
    import datetime as dt
    from app.forex_news import parse_investing_payload

    store = {
        "props": {"pageProps": {"state": {"economicCalendarStore": {
            "calendarEventsByDate": {
                "2026-10-10": [
                    {"importance": "3", "eventId": 111, "event": "CB Consumer Confidence",
                     "currency": "USD", "country": "United States",
                     "time": "2026-10-10T14:00:00Z", "forecast": "98.0",
                     "previous": "97.4", "actual": "99.2"},
                    {"importance": "2", "eventId": 222, "event": "German Industrial Production",
                     "currency": "EUR", "country": "Germany",
                     "time": "2026-10-10T06:00:00Z", "actual": "1.2%"},
                    # 1 yıldız -> elenir.
                    {"importance": "1", "eventId": 333, "event": "Some Low Impact",
                     "currency": "USD", "time": "2026-10-10T09:00:00Z", "actual": "5"},
                    # Başlıksız -> elenir.
                    {"importance": "3", "eventId": 444, "event": "",
                     "currency": "USD", "time": "2026-10-10T10:00:00Z"},
                ]
            }
        }}}}
    }
    html = (
        '<html><body><script type="application/json">'
        + json.dumps(store)
        + "</script></body></html>"
    )

    now = dt.datetime(2026, 10, 10, 20, 0, tzinfo=dt.timezone.utc)
    events = parse_investing_payload(html, now_utc=now)

    assert len(events) == 2
    ids = {e["id"] for e in events}
    # Kararlı kimlik kaynağın `eventId`'sinden gelir (hash() DEĞİL).
    assert ids == {"cal-inv-111", "cal-inv-222"}

    conf = next(e for e in events if e["id"] == "cal-inv-111")
    assert conf["original_title"] == "CB Consumer Confidence"
    assert (conf["forecast"], conf["previous"], conf["actual"]) == ("98.0", "97.4", "99.2")
    assert conf["stars"] == 3
    assert conf["status"] == "Açıklandı"
    assert conf["is_passed"] is True
    assert conf["source"] == "investing"
    assert "scenario" in conf and "bullish_trigger" in conf["scenario"]

    ind = next(e for e in events if e["id"] == "cal-inv-222")
    assert ind["forecast"] == "—"
    assert ind["is_passed"] is True
    assert ind["stars"] == 2


def test_parse_investing_payload_handles_bad_input():
    from app.forex_news import parse_investing_payload

    assert parse_investing_payload("") == []
    assert parse_investing_payload("<html><body>yük yok</body></html>") == []
    assert parse_investing_payload("<html><body><script>bozuk json{</script></body></html>") == []


def test_parse_investing_payload_future_event_not_passed():
    import datetime as dt
    from app.forex_news import parse_investing_payload

    store = {"props": {"pageProps": {"state": {"economicCalendarStore": {
        "calendarEventsByDate": {"2026-10-10": [
            {"importance": "3", "eventId": 555, "event": "Fed Interest Rate Decision",
             "currency": "USD", "time": "2026-10-10T23:00:00Z", "actual": "—"},
        ]}
    }}}}}
    html = "<script>" + json.dumps(store) + "</script>"

    now = dt.datetime(2026, 10, 10, 12, 0, tzinfo=dt.timezone.utc)
    events = parse_investing_payload(html, now_utc=now)
    assert len(events) == 1
    assert events[0]["is_passed"] is False
    assert events[0]["status"] == "Bekleniyor"


# ============================================================================
# BAYAT DB SATIRI TEMİZLİĞİ (saf karar fonksiyonu)
# ============================================================================

def test_should_prune_economic_calendar_floor():
    from app.database import _should_prune_economic_calendar, CALENDAR_PRUNE_FLOOR

    assert _should_prune_economic_calendar(CALENDAR_PRUNE_FLOOR) is True
    assert _should_prune_economic_calendar(CALENDAR_PRUNE_FLOOR + 10) is True
    # Eşik altı -> temizlik YOK (sağlayıcı kısmen çökmüşken takvimi silme).
    assert _should_prune_economic_calendar(CALENDAR_PRUNE_FLOOR - 1) is False
    assert _should_prune_economic_calendar(0) is False


def test_dynamic_fields_fill_outcome_for_legacy_row():
    """ESKİ veritabanı satırı taklidi: `outcome`/`has_data` anahtarları YOK.
    Bu fonksiyon her okuma yolunda çağrıldığı için ilk okumada dolmalıdır."""
    from app.forex_news import _update_event_dynamic_fields

    legacy = {
        "id": "legacy-1",
        "title": "ABD TÜFE",
        "original_title": "CPI YoY",
        "date_iso": "2026-10-09T12:30:00Z",
        "forecast": "3.0%",
        "previous": "2.9%",
        "actual": "3.2%",
    }
    assert "outcome" not in legacy and "has_data" not in legacy
    _update_event_dynamic_fields([legacy])
    assert legacy["has_data"] is True
    assert legacy["outcome"]["side"] == "bullish"
    assert legacy["outcome"]["basis"] == "forecast"
    assert legacy["status"] == "Açıklandı"


def test_dynamic_fields_outcome_without_date_iso():
    """`outcome` VERİ türevlidir — `date_iso` olmadan da hesaplanmalıdır
    (hesap `if date_iso:` bloğunun dışındadır)."""
    from app.forex_news import _update_event_dynamic_fields

    no_date = {
        "id": "no-date-1",
        "title": "ABD İstihdam",
        "original_title": "Non-Farm Payrolls",
        "forecast": "180K",
        "previous": "170K",
        "actual": "210K",
    }
    _update_event_dynamic_fields([no_date])
    assert no_date["outcome"] is not None
    assert no_date["outcome"]["side"] == "bullish"

    # Hiç veri yoksa: has_data False, outcome None, durum alanlarına dokunulmaz.
    empty = {"id": "empty-1", "title": "X", "forecast": "—", "previous": "—", "actual": "—"}
    _update_event_dynamic_fields([empty])
    assert empty["has_data"] is False
    assert empty["outcome"] is None

