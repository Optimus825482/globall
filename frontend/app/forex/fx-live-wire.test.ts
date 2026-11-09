import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * MT5 → PANEL CANLI YAYINI — regresyon kilidi (2026-11-09).
 *
 * Öncesi: köprü 1,5 sn'de bir veri yazıyordu ama panel REST'i 3 sn'de bir
 * yokluyordu (ortalama ~2,5 sn, en kötü ~4,5 sn bayat). Artık WS `fx_state`
 * yayını var; yoklama güvenlik ağı.
 *
 * EN SİNSİ TUZAK: `liveSocket.ts` içindeki `UNCONSUMED_LIVE_TYPES` bir tipi
 * ELER. `fx_state` oraya girerse yayın sessizce ölür — derleme geçer, sayfa
 * çalışır, sadece veri hiç güncellenmez. Bu test onu engeller.
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "..", "..");

const read = (...p: string[]) => readFileSync(path.join(FRONTEND, ...p), "utf8");

const SOCKET = read("app", "lib", "liveSocket.ts");
const PORTFOLIO = read("app", "forex", "portfolio", "page.tsx");
const ISLEMLER = read("app", "forex", "islemler", "page.tsx");
const ANA_SAYFA = read("app", "page.tsx");
const METAMOBIL = read("app", "forex", "metamobil", "page.tsx");
const BTC_GOLD = read("app", "forex", "btc-gold", "page.tsx");
const MULTI_CHART = read("app", "charts", "MultiChartCard.tsx");
const FX_NATIVE_CHART = read("app", "forex", "components", "ForexNativeChart.tsx");
const RADAR_MODAL = read("app", "forex", "components", "ForexRadarModal.tsx");

describe("WS kanalı yeni tipleri ELİYOR mu", () => {
  it("fx_state ve fx_trade_closed elenen listede OLMAMALI", () => {
    const block = SOCKET.slice(
      SOCKET.indexOf("UNCONSUMED_LIVE_TYPES"),
      SOCKET.indexOf("type MessageListener"),
    );
    expect(block).not.toContain("fx_state");
    expect(block).not.toContain("fx_trade_closed");
  });

  it("tickers hâlâ eleniyor (denetim #53 davranışı korunmalı)", () => {
    expect(SOCKET).toContain('"tickers"');
  });
});

describe("Portföy sayfası — canlı yayın", () => {
  it("fx_state'i abone ve REST ile AYNI reducer'dan geçiriyor", () => {
    expect(PORTFOLIO).toContain("useLiveMessages");
    expect(PORTFOLIO).toContain('message.type === "fx_state"');
    expect(PORTFOLIO).toContain("applyStatus(message.data)");
    // reducer tek: hem polling hem WS aynı fonksiyonu çağırır
    expect(PORTFOLIO).toContain("applyStatus(res)");
  });

  it("kapanan işlem olayında listeyi tazeliyor", () => {
    expect(PORTFOLIO).toContain('message.type === "fx_trade_closed"');
  });

  it("yoklama güvenlik ağına çekildi (3 sn değil)", () => {
    expect(PORTFOLIO).toContain("usePolling(fetchStatus, 15000)");
    expect(PORTFOLIO).not.toContain("usePolling(fetchStatus, 3000)");
  });
});

describe("İşlemler sayfası — canlı yayın", () => {
  it("fx_state aboneliği var", () => {
    expect(ISLEMLER).toContain("useLiveMessages");
    expect(ISLEMLER).toContain('message.type === "fx_state"');
  });

  it("açık pozisyonlar WS'ten geliyor", () => {
    const i = ISLEMLER.indexOf('message.type === "fx_state"');
    const block = ISLEMLER.slice(i, i + 900);
    expect(block).toContain("setOpenPositions");
  });

  it("işlem-sayısı KPI'sına dokunmuyor (tek kaynak kapanan işlem listesi)", () => {
    const i = ISLEMLER.indexOf('message.type === "fx_state"');
    const block = ISLEMLER.slice(i, i + 900);
    expect(block).toContain("open_positions_count");
    expect(block).not.toContain("total_trades:");
    expect(block).not.toContain("win_rate:");
  });

  it("kapanan işlem olayında yeniden çekiyor ve yoklama 15 sn", () => {
    expect(ISLEMLER).toContain('message.type === "fx_trade_closed"');
    expect(ISLEMLER).toContain("usePolling(() => fetchData(true), 15000)");
    expect(ISLEMLER).not.toContain("usePolling(() => fetchData(true), 3000)");
  });
});

// ── Tam envanter: canlı açık işlem gösteren HER sayfa + grafikler (2026-11-09) ──
// Kullanıcı isteği: "canlı açık işlemlerin olduğu tüm sayfaları ve grafikleri buna
// bağla". Yeni bir sayfa eklenip bağlanmazsa bu liste kırılır.
describe("Ana sayfa", () => {
  it("fx_state + fx_trade_closed aboneliği ve 15 sn güvenlik ağı", () => {
    expect(ANA_SAYFA).toContain("useLiveMessages");
    expect(ANA_SAYFA).toContain('message.type === "fx_state"');
    expect(ANA_SAYFA).toContain('message.type === "fx_trade_closed"');
    expect(ANA_SAYFA).toContain("usePolling(() => fetchData(true), 15000)");
    expect(ANA_SAYFA).not.toContain("usePolling(() => fetchData(true), 4000)");
  });
});

describe("MetaMobil", () => {
  it("fx_state aboneliği; hesap reducer'ı paylaşımlı", () => {
    expect(METAMOBIL).toContain('message.type === "fx_state"');
    // REST ve WS aynı reducer'ı çağırır (iki ayrı hesap = panel kendi içinde çelişir)
    expect(METAMOBIL).toContain("applyAccountStatus(statusData)");
    expect(METAMOBIL).toContain("applyAccountStatus(res)");
    expect(METAMOBIL).toContain("usePolling(refreshAllData, 15000)");
  });
});

describe("BTC-Gold kokpiti", () => {
  it("fx_state + fx_ticks aboneliği ve 15 sn güvenlik ağı", () => {
    expect(BTC_GOLD).toContain('message.type === "fx_state"');
    expect(BTC_GOLD).toContain('message.type === "fx_ticks"');
    expect(BTC_GOLD).toContain("applyStatus(res)");
    expect(BTC_GOLD).toContain("usePolling(fetchAllData, 15000)");
  });
});

describe("Grafikler", () => {
  it("MultiChartCard canlı `kline` yayınını tüketiyor", () => {
    expect(MULTI_CHART).toContain("useLiveMessages");
    expect(MULTI_CHART).toContain('message?.type !== "kline"');
    expect(MULTI_CHART).toContain("priceSnapshotFromBars");
  });

  it("fiyat özeti TEK uygulama (yoklama ve canlı akış aynı fonksiyon)", () => {
    // İki ayrı hesap olsaydı panel grafikle çelişirdi
    const defs = MULTI_CHART.match(/function priceSnapshotFromBars/g) || [];
    expect(defs.length).toBe(1);
    const uses = MULTI_CHART.match(/priceSnapshotFromBars\(/g) || [];
    expect(uses.length).toBeGreaterThanOrEqual(3);   // 1 tanım + 2 çağrı
  });

  it("ForexNativeChart tick uygulaması REST+WS için ortak ve yoklama 15 sn", () => {
    expect(FX_NATIVE_CHART).toContain('message?.type !== "fx_ticks"');
    expect(FX_NATIVE_CHART).toContain("applyTicker(");
    expect(FX_NATIVE_CHART).toContain("}, 15000);");
    expect(FX_NATIVE_CHART).not.toContain("}, 2500);");
  });
});

describe("Radar bildirim modalı", () => {
  it("işlem açıldığı an popup kapanıyor (WS), karar mantığı tek yerde", () => {
    expect(RADAR_MODAL).toContain("closeIfPositionOpened");
    expect(RADAR_MODAL).toContain('message?.type === "fx_state"');
    expect(RADAR_MODAL).toContain("usePolling(pollActiveStatus, activeSignal ? 15000 : null)");
  });
});
