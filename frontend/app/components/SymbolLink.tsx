// 2026-10-07: Global uygulaması FOREX-only oldu; `/charts` (kripto mum grafiği)
// sayfası kaldırıldı. Bu bileşen eskiden sembole tıklanınca o sayfayı açardı ve
// şimdi 404'e giderdi. Sembol artık düz metin olarak gösterilir — çağıranların
// tümü (bildirim listesi, alarm paneli, chat önerileri) yalnızca etiket
// istiyordu; gezinti beklentisi yoktu.
type SymbolLinkProps = {
  symbol?: string | null;
  className?: string;
  timeframe?: string;
  newTab?: boolean;
};

export default function SymbolLink({ symbol, className = "font-mono text-white" }: SymbolLinkProps) {
  const value = String(symbol || "").replace(/_/g, "").toUpperCase();
  if (!value) return null;
  return <span className={className}>{value}</span>;
}
