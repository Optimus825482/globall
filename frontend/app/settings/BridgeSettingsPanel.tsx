"use client";

import { useEffect, useState, useCallback } from "react";
import { API_BASE, apiRequest } from "../lib/api";
import { useVisibleInterval } from "../lib/useVisibleInterval";

interface BridgeStats {
  total_dispatched: number;
  total_success: number;
  total_failed: number;
  total_skipped_cooldown: number;
  total_skipped_disabled: number;
  total_skipped_score: number;
  last_dispatched_at: number | null;
  last_success_at: number | null;
  last_error: string | null;
}

interface BridgeHistoryItem {
  event_id: string;
  timestamp: number;
  global_symbol: string;
  base_asset: string;
  tr_symbol: string;
  signal_type: string;
  score: number | null;
  price: number | null;
  ok: boolean;
  status_code: number | null;
  latency_ms: number;
  error: string | null;
}

interface BridgeStatus {
  enabled: boolean;
  url: string;
  secret_configured: boolean;
  masked_secret: string;
  min_score: number;
  cooldown_sec: number;
  stats: BridgeStats;
  recent_history: BridgeHistoryItem[];
}

export default function BridgeSettingsPanel() {
  const [data, setData] = useState<BridgeStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form states
  const [enabled, setEnabled] = useState(true);
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [minScore, setMinScore] = useState("0");
  const [cooldownSec, setCooldownSec] = useState("10");
  const [saving, setSaving] = useState(false);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  // Ping test states
  const [pingSymbol, setPingSymbol] = useState("SOLUSDT");
  const [pinging, setPinging] = useState(false);
  const [pingResult, setPingResult] = useState<{
    ok: boolean;
    status_code?: number | null;
    latency_ms?: number;
    response?: string;
    error?: string;
    target_url?: string;
  } | null>(null);

  const fetchStatus = useCallback(async (isInitial = false) => {
    if (isInitial) setLoading(true);
    try {
      const res = await apiRequest(`${API_BASE}/api/bridge/status`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: BridgeStatus = await res.json();
      setData(json);
      if (isInitial) {
        setEnabled(json.enabled);
        setUrl(json.url || "");
        setMinScore(String(json.min_score ?? 0));
        setCooldownSec(String(json.cooldown_sec ?? 10));
      }
      setError(null);
    } catch (err: any) {
      setError(err.message || "Köprü durumu alınamadı.");
    } finally {
      if (isInitial) setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus(true);
  }, [fetchStatus]);

  // Otomatik canlı durum yenileme (her 4 saniyede bir, sekme görünürken)
  useVisibleInterval(() => {
    fetchStatus(false);
  }, 4000);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSavedMessage(null);
    try {
      const body: Record<string, any> = {
        enabled,
        url: url.trim(),
        min_score: parseFloat(minScore) || 0,
        cooldown_sec: parseFloat(cooldownSec) || 10,
      };
      if (secret.trim()) {
        body.secret = secret.trim();
      }

      const res = await apiRequest(`${API_BASE}/api/bridge/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `Kayıt başarısız (HTTP ${res.status})`);
      }

      setSavedMessage("✓ Ayarlar başarıyla güncellendi.");
      setSecret("");
      await fetchStatus(false);
      setTimeout(() => setSavedMessage(null), 3500);
    } catch (err: any) {
      alert("Hata: " + err.message);
    } finally {
      setSaving(false);
    }
  };

  const handlePing = async (sym?: string) => {
    const targetSymbol = sym || pingSymbol;
    setPinging(true);
    setPingResult(null);
    try {
      const res = await apiRequest(`${API_BASE}/api/bridge/test-ping`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: targetSymbol }),
      });
      const json = await res.json();
      setPingResult(json);
      await fetchStatus(false);
    } catch (err: any) {
      setPingResult({
        ok: false,
        error: err.message || "Ağ isteği gerçekleştirilemedi.",
      });
    } finally {
      setPinging(false);
    }
  };

  const formatTimestamp = (ts: number | null) => {
    if (!ts) return "—";
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  if (loading && !data) {
    return (
      <div className="card bg-bunker-950 p-6">
        <p className="font-mono text-sm text-bunker-muted animate-pulse">
          Binance TR köprü durumu kontrol ediliyor...
        </p>
      </div>
    );
  }

  const isBridgeReady = data?.enabled && data?.url;
  const isHealthy = isBridgeReady && (!data?.stats.last_error || (data?.stats.total_success ?? 0) > 0);

  return (
    <div className="space-y-6">
      {/* 1. BAŞLIK VE CANLI DURUM KARTI */}
      <div className="card bg-bunker-950 border border-bunker-800 p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xl">🌉</span>
              <h2 className="font-mono text-base font-bold text-white tracking-wide">
                BİNANCE GLOBAL ➔ BİNANCE TR LİNK KÖPRÜSÜ
              </h2>
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-mono font-medium ${
                  !data?.enabled
                    ? "bg-bunker-800 text-bunker-muted border border-bunker-700"
                    : isHealthy
                    ? "bg-neon-green/15 text-neon-green border border-neon-green/30"
                    : "bg-neon-red/15 text-neon-red border border-neon-red/30"
                }`}
              >
                <span
                  className={`w-2 h-2 rounded-full ${
                    !data?.enabled
                      ? "bg-bunker-500"
                      : isHealthy
                      ? "bg-neon-green animate-pulse"
                      : "bg-neon-red"
                  }`}
                />
                {!data?.enabled
                  ? "KÖPRÜ KAPALI"
                  : isHealthy
                  ? "HABERLEŞME AKTİF"
                  : "İLETİM UYARISI"}
              </span>
            </div>
            <p className="text-xs text-bunker-muted max-w-3xl">
              Binance Global (USDT) yüksek hacimli kırılımları Binance TR (TRY) tahtasından birkaç saniye önce fiyatlar.
              Bu sekme üzerinden iki uygulamanın gerçek zamanlı bağlantı ve sinyal akışını izleyebilirsiniz.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => fetchStatus(false)}
              className="px-3 py-1.5 rounded-lg border border-bunker-700 bg-bunker-900 text-xs font-mono text-bunker-muted hover:text-white hover:border-bunker-600 transition"
              title="Verileri manuel yenile"
            >
              🔄 Yenile
            </button>
            <button
              onClick={() => handlePing()}
              disabled={pinging}
              className="px-4 py-1.5 rounded-lg border border-neon-green/40 bg-neon-green/15 text-xs font-mono font-bold text-neon-green hover:bg-neon-green/25 transition disabled:opacity-50 flex items-center gap-1.5"
            >
              {pinging ? (
                <>
                  <span className="w-3 h-3 border-2 border-neon-green border-t-transparent rounded-full animate-spin" />
                  Ping Gönderiliyor...
                </>
              ) : (
                <>🧪 Canlı Ping Testi</>
              )}
            </button>
          </div>
        </div>

        {/* PING TEST SONUCU BİLDİRİMİ */}
        {pingResult && (
          <div
            className={`mt-4 p-3.5 rounded-lg border font-mono text-xs flex items-start justify-between gap-3 ${
              pingResult.ok
                ? "bg-neon-green/10 border-neon-green/40 text-neon-green"
                : "bg-neon-red/10 border-neon-red/40 text-neon-red"
            }`}
          >
            <div className="space-y-1">
              <div className="font-bold flex items-center gap-2">
                {pingResult.ok ? "✓ BAĞLANTI BAŞARILI (PONG ALINDI)" : "✕ BAĞLANTI BAŞARISIZ"}
                {pingResult.status_code && (
                  <span className="px-1.5 py-0.5 rounded bg-black/40 text-[11px]">
                    HTTP {pingResult.status_code}
                  </span>
                )}
                {pingResult.latency_ms !== undefined && (
                  <span className="px-1.5 py-0.5 rounded bg-black/40 text-[11px]">
                    ⏱ {pingResult.latency_ms} ms
                  </span>
                )}
              </div>
              <p className="text-white/80 break-all text-[11px]">
                Hedef: {pingResult.target_url || data?.url}
              </p>
              {pingResult.response && (
                <p className="text-white/90 bg-black/30 p-2 rounded text-[11px] mt-1 font-mono">
                  Yanıt: {pingResult.response}
                </p>
              )}
              {pingResult.error && (
                <p className="text-neon-red/90 bg-black/30 p-2 rounded text-[11px] mt-1">
                  Hata detayı: {pingResult.error}
                </p>
              )}
            </div>
            <button
              onClick={() => setPingResult(null)}
              className="text-bunker-muted hover:text-white px-2 py-0.5 text-xs"
            >
              ✕
            </button>
          </div>
        )}
      </div>

      {/* 2. CANLI İSTATİSTİK SAYAÇLARI */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="card bg-bunker-950 border border-bunker-800 p-4">
          <p className="text-[11px] font-mono text-bunker-muted uppercase">Toplam İletilen</p>
          <p className="text-2xl font-mono font-bold text-white mt-1">
            {data?.stats.total_dispatched ?? 0}
          </p>
          <span className="text-[10px] text-bunker-muted">Tüm sinyal tetiklemeleri</span>
        </div>

        <div className="card bg-bunker-950 border border-bunker-800 p-4">
          <p className="text-[11px] font-mono text-neon-green uppercase">Başarılı İletim</p>
          <p className="text-2xl font-mono font-bold text-neon-green mt-1">
            {data?.stats.total_success ?? 0}
          </p>
          <span className="text-[10px] text-bunker-muted">HTTP 200 teslim</span>
        </div>

        <div className="card bg-bunker-950 border border-bunker-800 p-4">
          <p className="text-[11px] font-mono text-neon-red uppercase">Hata / Başarısız</p>
          <p className="text-2xl font-mono font-bold text-neon-red mt-1">
            {data?.stats.total_failed ?? 0}
          </p>
          <span className="text-[10px] text-bunker-muted">Ulaşılamayan / Reddedilen</span>
        </div>

        <div className="card bg-bunker-950 border border-bunker-800 p-4">
          <p className="text-[11px] font-mono text-amber-400 uppercase">Cooldown Filtresi</p>
          <p className="text-2xl font-mono font-bold text-amber-400 mt-1">
            {data?.stats.total_skipped_cooldown ?? 0}
          </p>
          <span className="text-[10px] text-bunker-muted">Spam/mükerrer engeli</span>
        </div>

        <div className="card bg-bunker-950 border border-bunker-800 p-4 col-span-2 md:col-span-1">
          <p className="text-[11px] font-mono text-bunker-muted uppercase">Son İletim Saati</p>
          <p className="text-lg font-mono font-bold text-white mt-1.5">
            {formatTimestamp(data?.stats.last_dispatched_at ?? null)}
          </p>
          <span className="text-[10px] text-bunker-muted">
            {data?.stats.last_success_at ? "Son başarı: " + formatTimestamp(data.stats.last_success_at) : "Henüz işlem yok"}
          </span>
        </div>
      </div>

      {/* 3. GERÇEK ZAMANLI SİNYAL GEÇMİŞİ TABLOSU */}
      <div className="card bg-bunker-950 border border-bunker-800 p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-mono text-sm font-bold text-white uppercase tracking-wider">
              Canlı İletim Akışı (Son 100 Sinyal)
            </h3>
            <p className="text-xs text-bunker-muted mt-0.5">
              Global motorundan Binance TR klonuna aktarılan son sinyaller ve yanıt kodları.
            </p>
          </div>
          <span className="font-mono text-xs text-bunker-muted">
            {data?.recent_history?.length || 0} kayıt
          </span>
        </div>

        {(!data?.recent_history || data.recent_history.length === 0) ? (
          <div className="p-8 text-center border border-dashed border-bunker-800 rounded-lg text-bunker-muted text-xs font-mono">
            Henüz iletilen bir sinyal kaydı bulunmuyor.
            <br />
            Yukarıdaki <strong className="text-neon-green">"Canlı Ping Testi"</strong> butonuna basarak iki uygulamanın haberleşmesini hemen doğrulayabilirsiniz.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs border-collapse">
              <thead>
                <tr className="border-b border-bunker-800 text-[11px] text-bunker-muted bg-bunker-900/40">
                  <th className="py-2.5 px-3">Zaman</th>
                  <th className="py-2.5 px-3">Global Sembol</th>
                  <th className="py-2.5 px-3">➔ TR Karşılığı</th>
                  <th className="py-2.5 px-3">Sinyal Türü</th>
                  <th className="py-2.5 px-3">Skor / Fiyat</th>
                  <th className="py-2.5 px-3">Gecikme</th>
                  <th className="py-2.5 px-3">Durum</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bunker-900">
                {data.recent_history.slice(0, 25).map((item) => (
                  <tr key={item.event_id} className="hover:bg-bunker-900/30 transition">
                    <td className="py-2 px-3 text-bunker-muted">
                      {formatTimestamp(item.timestamp)}
                    </td>
                    <td className="py-2 px-3 font-bold text-white">
                      {item.global_symbol}
                    </td>
                    <td className="py-2 px-3 font-bold text-neon-green">
                      {item.tr_symbol}
                    </td>
                    <td className="py-2 px-3">
                      <span className="px-2 py-0.5 rounded bg-bunker-900 border border-bunker-700 text-[11px] text-white/90">
                        {item.signal_type}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-white/90">
                      {item.score !== null ? `${Number(item.score).toFixed(1)}p` : "—"}{" "}
                      {item.price ? <span className="text-bunker-muted text-[11px]">(${Number(item.price).toFixed(2)})</span> : null}
                    </td>
                    <td className="py-2 px-3 text-bunker-muted">
                      {item.latency_ms} ms
                    </td>
                    <td className="py-2 px-3">
                      {item.ok ? (
                        <span className="inline-flex items-center gap-1 text-neon-green font-bold">
                          ✓ {item.status_code || 200} OK
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-neon-red font-bold" title={item.error || "Hata"}>
                          ✕ {item.status_code ? `HTTP ${item.status_code}` : "Bağlantı Hatası"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 4. KÖPRÜ YAPILANDIRMA VE YÖNETİM PANELİ */}
      <div className="card bg-bunker-950 border border-bunker-800 p-5">
        <div className="mb-4">
          <h3 className="font-mono text-sm font-bold text-white uppercase tracking-wider">
            Köprü Yapılandırması ve Parametreler
          </h3>
          <p className="text-xs text-bunker-muted mt-0.5">
            Burada yapılan değişiklikler sunucuyu yeniden başlatmadan anında veritabanına işlenir ve devreye girer.
          </p>
        </div>

        <form onSubmit={handleSave} className="space-y-4">
          {/* Aktif / Pasif Toggle */}
          <div className="flex items-center justify-between p-3 rounded-lg border border-bunker-800 bg-bunker-900/50">
            <div>
              <label className="text-xs font-mono font-bold text-white block">
                Sinyal Köprüsünü Etkinleştir
              </label>
              <span className="text-[11px] text-bunker-muted">
                Kapatılırsa Global alarmları ve sinyalleri Binance TR'ye iletilmez.
              </span>
            </div>
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="w-5 h-5 accent-neon-green cursor-pointer rounded"
            />
          </div>

          {/* Hedef Webhook URL */}
          <div className="space-y-1">
            <label className="text-xs font-mono text-bunker-muted block">
              Binance TR Hedef Webhook URL:
            </label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://scalper.erkanerdem.online/api/bridge/global-signal veya http://gateway/api/bridge/global-signal"
              className="w-full bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon-green/60"
            />
            <span className="text-[10px] text-bunker-muted block">
              Örnek: Sunucu içi Docker ağında <code>http://gateway:80/api/bridge/global-signal</code> veya dış alan adı <code>https://scalper.erkanerdem.online/api/bridge/global-signal</code>
            </span>
          </div>

          {/* Güvenlik Gizli Anahtarı (X-Bridge-Secret) */}
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <label className="text-xs font-mono text-bunker-muted block">
                Köprü Doğrulama Anahtarı (X-Bridge-Secret):
              </label>
              <span className="text-[10px] font-mono text-bunker-muted">
                Mevcut: {data?.secret_configured ? <span className="text-neon-green">Tanımlı ({data.masked_secret})</span> : <span className="text-amber-400">Tanımsız</span>}
              </span>
            </div>
            <div className="relative">
              <input
                type={showSecret ? "text" : "password"}
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                placeholder="Değiştirmek istemiyorsanız boş bırakın"
                className="w-full bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon-green/60 pr-16"
              />
              <button
                type="button"
                onClick={() => setShowSecret(!showSecret)}
                className="absolute right-2 top-2 text-[10px] font-mono text-bunker-muted hover:text-white px-1.5 py-0.5 rounded bg-bunker-800"
              >
                {showSecret ? "Gizle" : "Göster"}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Minimum Skor Eşiği */}
            <div className="space-y-1">
              <label className="text-xs font-mono text-bunker-muted block">
                Minimum Radar/Sinyal Skoru (0 - 100):
              </label>
              <input
                type="number"
                min="0"
                max="100"
                step="1"
                value={minScore}
                onChange={(e) => setMinScore(e.target.value)}
                className="w-full bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon-green/60"
              />
              <span className="text-[10px] text-bunker-muted block">
                0 verilirse puanına bakılmaksızın tüm onaylı sinyaller iletilir.
              </span>
            </div>

            {/* Cooldown Süresi */}
            <div className="space-y-1">
              <label className="text-xs font-mono text-bunker-muted block">
                Mükerrer Bildirim Engeli (Saniye):
              </label>
              <input
                type="number"
                min="1"
                max="300"
                step="1"
                value={cooldownSec}
                onChange={(e) => setCooldownSec(e.target.value)}
                className="w-full bg-bunker-900 border border-bunker-700 rounded-lg px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-neon-green/60"
              />
              <span className="text-[10px] text-bunker-muted block">
                Aynı coinin peş peşe iletilerek TR tarafında spam oluşturmasını engeller (varsayılan: 10sn).
              </span>
            </div>
          </div>

          {/* Test Ping Sembolü ve Kaydet Butonu */}
          <div className="pt-2 flex flex-wrap items-center justify-between gap-3 border-t border-bunker-800">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-bunker-muted">Hızlı Test Sembolü:</span>
              <div className="flex items-center gap-1">
                {["SOLUSDT", "BTCUSDT", "PEPEUSDT", "AVAXUSDT"].map((sym) => (
                  <button
                    key={sym}
                    type="button"
                    onClick={() => {
                      setPingSymbol(sym);
                      handlePing(sym);
                    }}
                    disabled={pinging}
                    className="px-2 py-1 rounded bg-bunker-900 border border-bunker-700 hover:border-neon-green text-[11px] font-mono text-white"
                  >
                    {sym}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-3">
              {savedMessage && (
                <span className="font-mono text-xs text-neon-green font-bold animate-pulse">
                  {savedMessage}
                </span>
              )}
              <button
                type="submit"
                disabled={saving}
                className="min-h-10 px-6 rounded-lg border border-neon-green/50 bg-neon-green/20 text-neon-green font-mono text-xs font-bold hover:bg-neon-green/30 transition disabled:opacity-50"
              >
                {saving ? "Kaydediliyor..." : "AYARLARI KAYDET"}
              </button>
            </div>
          </div>
        </form>
      </div>

      {/* 5. LEAD-LAG STRATEJİ VE ÇALIŞMA MANTIĞI BİLGİ KARTI */}
      <div className="card bg-bunker-900/40 border border-bunker-800 p-4 text-xs font-mono space-y-2 text-bunker-muted">
        <p className="text-white font-bold flex items-center gap-1.5">
          <span>💡</span> ÖNCÜ-ARTÇI (LEAD-LAG) ÇALIŞMA MANTIĞI:
        </p>
        <p>
          1. <strong>Öncü Sinyal Üretimi:</strong> Binance Global spot tahtasındaki USDT hacmi çok yüksek olduğu için bir coindeki kırılımlar, balina girişleri ve ani momentumlar Binance TR'den <strong>2 ila 5 saniye</strong> önce başlar.
        </p>
        <p>
          2. <strong>Otomatik Sembol Eşleme:</strong> Global'de üretilen <code>SOLUSDT</code> sinyali taban varlığına (<code>SOL</code>) ayrıştırılarak Binance TR formatına (<code>SOLTRY</code>) dönüştürülür ve doğrudan TR uygulamasına iletilir.
        </p>
        <p>
          3. <strong>Sıfır Gecikmeli Webhook:</strong> Global analiz döngüsünü aksatmamak için istekler bağımsız HTTP havuzu üzerinden mikrosaniyeler içinde (non-blocking) fırlatılır.
        </p>
      </div>
    </div>
  );
}
