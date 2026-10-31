import sys
import asyncio
sys.path.insert(0, r"d:\PROJELLER\globall\backend")

from app.spot_monitor import get_active_strategies, get_spot_monitor_dashboard

async def main():
    strats = await get_active_strategies()
    print("Aktif Stratejiler Sayısı:", strats["count"])
    for s in strats["strategies"][:4]:
        print(f"Puan {s['score']}: {s['label']} | Override: {s.get('tp_sl_override')}")
    dash = await get_spot_monitor_dashboard()
    print("Dashboard Başarıyla Yüklendi! Sinyal Sayısı:", len(dash["signals"]))

if __name__ == "__main__":
    asyncio.run(main())
