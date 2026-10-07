// 2026-10-07: Global uygulaması YALNIZCA Forex & Emtia sunar.
// Kök yol (`/`) eskiden kripto spot dashboard'uydu; FOREX-only yapıda bu yüzey
// kaldırıldı. `/` hâlâ geçerli kalmalı çünkü PWA `start_url` ve hata
// sayfalarındaki "ANA SAYFAYA DÖN" bağlantıları buraya gelir — bu yüzden
// silmek yerine Forex radarına yönlendiriyoruz.
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/forex");
}
