// Borsaya bağlı varlık kontrolleri — borsa-bağımsız SAYFA katmanının parçası.
//
// Bu iki fonksiyon saf (pure) olduğu için burada yaşar ve test edilebilir.
// `page.tsx` (2478 satır) içinde kalsalardı test edilemezlerdi; 2026-09-27'de
// orada sabit `h.asset === "TRY"` yazıyordu ve Global örneğinde yanlış
// çalışıyordu.
//
// Neden `format.ts`'de değil: `format.ts` saf biçimlendirme (sayıyı metne
// çevir) içindir ve `QUOTE_ASSET`'ı build-time env'den okur. Buradaki
// fonksiyonlar ise borsa kimliğini parametre olarak ALIR — test TR, Global
// ve var olmayan üçüncü bir borsada aynı kodu çalıştırabilir. Build-time env
// testte değiştirilemez; parametre değiştirilebilir.

/**
 * Verilen varlık, bu borsanın nakit varlığı mı?
 *
 * Nakit varlık bir çiftin tabanı olamaz, alınamaz/satılamaz ve PnL'si
 * hesaplanmaz. Bu yüzden pozisyon tablolarından elenir, K/Z hesabına girmez
 * ve satış butonu açılmaz.
 *
 * Büyük/küçük harf normalize edilir (API karışık dönebilir) ve karşılaştırma
 * TAM EŞİTLİKTİR — `endsWith` kullanılsaydı "STRY" gibi bir varlık yanlışlıkla
 * nakit sayılırdı.
 */
export function isCashAsset(asset: string | null | undefined, quoteAsset: string): boolean {
  return String(asset ?? "").trim().toUpperCase() === String(quoteAsset ?? "").trim().toUpperCase();
}

/** `("BTC", "USDT")` → `"BTCUSDT"`. Quote'sü zaten içeriyorsa çiftlemez. */
export function cashSymbolLabel(base: string, quoteAsset: string): string {
  const value = String(base ?? "").trim().toUpperCase();
  const quote = String(quoteAsset ?? "").trim().toUpperCase();
  return value.endsWith(quote) ? value : `${value}${quote}`;
}
