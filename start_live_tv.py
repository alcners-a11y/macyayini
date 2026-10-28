import os
import sys
import time
import subprocess
import threading
import re
import requests

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

BRIDGE_TOPIC = "macyayini_bridge_a0419"

print("=" * 70)
print("⚽ CANLI FUTBOL TV VE CLOUDFLARE TÜNELİ BAŞLATILIYOR...")
print("=" * 70)

# 1. Python Flask Backend'ini başlat
backend_proc = subprocess.Popen(
    [sys.executable, "app.py"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)

# 2. Cloudflare Tunnel'ı başlat
cloudflared_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloudflared.exe")
tunnel_proc = subprocess.Popen(
    [cloudflared_bin, "tunnel", "--url", "http://localhost:5000"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="ignore"
)

tunnel_url = None

print("\n⏳ Cloudflare Güvenli Bağlantısı Kuruluyor...")

for line in iter(tunnel_proc.stdout.readline, ''):
    match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
    if match and not tunnel_url:
        tunnel_url = match.group(0)
        
        # 3. Firebase yönlendirmesini otomatik güncelle
        try:
            requests.post(
                f"https://ntfy.sh/{BRIDGE_TOPIC}",
                data=tunnel_url,
                headers={"Cache": "yes"},
                timeout=5
            )
        except Exception:
            pass

        print("\n" + "=" * 70)
        print("🎉 CANLI YAYIN PLATFORMUNUZ HAZIR!")
        print("=" * 70)
        print("👉 HER ZAMAN KULLANACAĞINIZ SABİT & AKILDA KALICI ADRESİNİZ:")
        print(f"\n   \033[92m\033[1mhttps://macyayini-a0419.web.app\033[0m\n")
        print(f"🔗 Arka Plan Tüneli (Otomatik Yönlendirilir): {tunnel_url}")
        print("=" * 70)
        print("💡 Telefonunuza sadece 'macyayini-a0419.web.app' linkini kaydetmeniz yeterlidir!")
        print("🚫 Bölge engeli (Geo-block) yoktur, Türkiye internetiniz üzerinden çalışır.")
        print("=" * 70)
        print("\n(Kapatmak için bu pencereyi kapatabilir veya Ctrl+C yapabilirsiniz)\n")
        
        try:
            import webbrowser
            webbrowser.open("https://macyayini-a0419.web.app")
        except Exception:
            pass

try:
    tunnel_proc.wait()
except KeyboardInterrupt:
    print("\nKapatılıyor...")
    backend_proc.terminate()
    tunnel_proc.terminate()
