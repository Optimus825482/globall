import AppLoader from "./components/AppLoader";

export default function Loading() {
  return (
    <AppLoader
      variant="default"
      label="SAYFA YÜKLENİYOR…"
      sublabel="SCALPER GLOBAL AGENT arayüzü hazırlanıyor"
      minHeight="min-h-[50vh]"
    />
  );
}

