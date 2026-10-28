import requests
import websocket
import json
import time
import sys
import threading
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

import os
import http.server
import socketserver
import urllib.parse

# --- CONFIGURATION ---
PARTNER_ID = "44ba10e5-7df2-47ab-a44d-dc93803c7a6e"
REST_BASE = "https://api-gateway.top-parser.com"
WS_URL = f"wss://api-gateway.top-parser.com/push-server-v2/?Language=tr-TR&externalPartnerId={PARTNER_ID}&EIO=4&transport=websocket"

# 1win giriş token'ınız varsa buraya ekleyebilirsiniz (otomatik imzalı yayın linki üretir)
USER_TOKEN = os.environ.get("WIN1_TOKEN", "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIxd2luIiwianRpIjoiTmVhbXgzVHJvMVJ6c0U0SUZOaEMiLCJ0ZW5hbnRJZCI6MSwiaWF0IjoxNzkzMTAyNTcwLCJleHAiOjE3OTMxODg5NzAsInN1YiI6IjM4NDc2MzU2MCJ9.cyyOA8RxISbckF6o_lrrHlvkFkwPcEECdpu8g3KzOvhAwiwekjcMsVeWbMy9EHDN5ClWFEOjlRTWypfvXRHcfw")

HEADERS = {
    "Origin": "https://1wtlrj.life",
    "Referer": "https://1wtlrj.life/",
    "x-external-partner-id": PARTNER_ID,
    "x-lang": "tr-TR",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_signed_broadcast_url(match_id, broadcast_id):
    """Kullanıcı token'ı varsa 1win API'sinden imzalı (sign'lı) doğrudan çalışan yayın URL'sini alır."""
    if not USER_TOKEN or not broadcast_id:
        return None
    try:
        r = requests.post(
            f"{REST_BASE}/broadcast/get-url",
            json={"matchId": match_id, "broadcastId": str(broadcast_id)},
            params={"l": "tr-TR", "p": PARTNER_ID},
            headers={**HEADERS, "token": USER_TOKEN},
            timeout=5
        )
        res = r.json()
        if "result" in res and "url" in res["result"]:
            return res["result"]["url"]
    except Exception:
        pass
    return None

# --- YAYIN OYNATICI (REFERER KORUMASINI KALDIRAN LOCAL SERVER) ---
LOCAL_PLAYER_PORT = 5055

HTML_PLAYER_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="referrer" content="always">
    <title>1win Canlı Yayın İzleyici</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: #0b0e14; font-family: sans-serif; height: 100vh; overflow: hidden; display: flex; flex-direction: column; }}
        .bar {{ background: #161b26; color: #fff; padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #283042; }}
        .bar h3 {{ font-size: 15px; color: #00b0ff; }}
        .player-container {{ flex: 1; width: 100%; height: 100%; }}
        iframe {{ width: 100%; height: 100%; border: none; }}
    </style>
</head>
<body>
    <div class="bar">
        <h3>⚽ 1win Canlı Maç Yayını</h3>
        <span style="color:#aaa; font-size:13px;">Canlı Yayın Aktif</span>
    </div>
    <div class="player-container">
        <iframe src="{stream_url}" allow="autoplay; fullscreen" allowfullscreen></iframe>
    </div>
</body>
</html>
"""

class LocalPlayerHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/watch":
            qs = urllib.parse.parse_qs(parsed.query)
            stream_url = qs.get("url", [""])[0]
            if stream_url:
                html = HTML_PLAYER_TEMPLATE.format(stream_url=stream_url)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
                return
        self.send_response(404)
        self.end_headers()
    def log_message(self, format, *args):
        pass  # sessiz mod

def start_local_player_server():
    try:
        class ReusableTCPServer(socketserver.TCPServer):
            allow_reuse_address = True
        httpd = ReusableTCPServer(("", LOCAL_PLAYER_PORT), LocalPlayerHandler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
    except Exception:
        pass

start_local_player_server()

# Filtrelenecek sanal, e-spor, tekrar ve mini futbol anahtar kelimeleri
EXCLUDE_KEYWORDS = [
    "short-football", "world-cup-penalty", "penalty-shootout", "ehighlights",
    "vi-highlights", "replays", "esportsbattle", "dart", "h2h-gg-league",
    "cyberfifa", "ereplays", "esport", "cyber", "volta",
    "2x4-min", "2x3-min", "2x5-min", "3x3", "2x2"
]

def is_real_football(match):
    """Sadece gerçek futbol maçlarını kabul eder, sanal/espor/replay liglerini filtreler."""
    service = str(match.get("service") or match.get("serviceV2") or "").upper()
    if service and "LIVE" not in service:
        return False
        
    if match.get("isCyber") or match.get("isVirtual") or match.get("isEsport"):
        return False
        
    cat_slug = str(match.get("category", {}).get("slug", "")).lower()
    cat_name = str(match.get("category", {}).get("name", "")).lower()
    tour_slug = str(match.get("tournament", {}).get("slug", "")).lower()
    tour_name = str(match.get("tournament", {}).get("name", "")).lower()
    match_name = str(match.get("name", "")).lower()
    home_name = str(match.get("homeTeam", {}).get("name", "")).lower()
    away_name = str(match.get("awayTeam", {}).get("name", "")).lower()
    
    combined = f"{cat_slug} {cat_name} {tour_slug} {tour_name} {match_name} {home_name} {away_name}"
    for kw in EXCLUDE_KEYWORDS:
        if kw in combined:
            return False
            
    if "(v)" in home_name or "(v)" in away_name:
        return False
        
    return True

# 1. Fetch active live football matches (sportId=18, service=LIVE)
print("1. Canlı gerçek futbol maçları REST API'den çekiliyor...")
res = requests.post(
    f"{REST_BASE}/matches/get-many",
    json={"sportId": 18, "isLive": True, "service": "LIVE", "limit": 100},
    params={"l": "tr-TR", "p": PARTNER_ID},
    headers=HEADERS,
    timeout=10
)

matches_data = res.json().get("result", {}).get("items", [])
active_matches = {}
match_ids = []

for m in matches_data:
    mid = m.get("id")
    if mid and not m.get("closed", False) and is_real_football(m):
        home = m.get("homeTeam", {}).get("name", "Ev Sahibi")
        away = m.get("awayTeam", {}).get("name", "Deplasman")
        tournament = m.get("tournament", {}).get("slug", "Lig")
        category = m.get("category", {}).get("slug", "")
        
        active_matches[mid] = {
            "id": mid,
            "home": home,
            "away": away,
            "name": f"{home} vs {away}",
            "tournament": tournament,
            "category": category,
            "status": "Canlı",
            "minute": "",
            "match_time_ms": None,
            "score": "- vs -",
            "odds_1x2": {},             # 1, X, 2 (Maç Sonucu)
            "odds_totals": {},          # Maç Toplam Gol (Standart: 0.5, 1.5, 2.0, 2.5, 3.5...)
            "odds_home_totals": {},     # Ev Sahibi Toplam Gol (Alt / Üst)
            "odds_away_totals": {},     # Deplasman Toplam Gol (Alt / Üst)
            "odds_btts": {},            # İki Takım da Gol Atar (Var / Yok)
            "broadcast": None,          # Canlı Yayın (Stream Linki)
            "live_tracker": None,       # Canlı Maç Takipçisi (Radar Animasyonu)
            "all_odds": {}
        }
        match_ids.append(mid)

print(f"-> {len(active_matches)} adet gerçek canlı maç bulundu (Sanal/E-spor/Replay filtrelendi).\n")

if not match_ids:
    print("Aktif maç bulunamadı.")
    sys.exit()

# Oran meta-verilerini (ID -> Market, Baraj, Tip) hafızada tutan registry
# Canlı delta güncellemelerinde server sadece ID ve yeni oranı gönderir
odds_meta_registry = {}

# 2. WebSocket listener to receive real-time odds, minute, & live scores
def on_message(ws, message):
    # Engine.IO Handshake (0) -> Socket.IO Connect (40)
    if message.startswith("0"):
        ws.send("40")
        
    # Socket.IO Connect Ack (40) -> Abone ol
    elif message.startswith("40"):
        sub_info = {
            "messageType": "subscribe-match-info",
            "data": {"matchIds": match_ids}
        }
        # isBaseOddsGroups: False -> Tüm alt/üst barajları, ev/dep toplamları, vb. açılır
        sub_odds = {
            "messageType": "subscribe-match-odds",
            "data": {"matchIds": match_ids, "isBaseOddsGroups": False}
        }
        ws.send(f'42{json.dumps(["subscribe", sub_info])}')
        ws.send(f'42{json.dumps(["subscribe", sub_odds])}')
        
    elif message == "2":
        ws.send("3")
        
    elif message.startswith("42"):
        try:
            payload = json.loads(message[2:])
            event_name = payload[0]
            event_data = payload[1]
            
            if event_name == "u":
                data = event_data.get("data", {})
                mid = data.get("matchId")
                if mid in active_matches:
                    match_obj = active_matches[mid]
                    
                    # 0. Canlı Yayın (Broadcast) ve Maç Takipçisi (LiveTracker)
                    if "broadcast" in data and data["broadcast"]:
                        match_obj["broadcast"] = data["broadcast"]
                    if "liveTracker" in data and data["liveTracker"]:
                        match_obj["live_tracker"] = data["liveTracker"]
                        
                    # 1. Devre ve Durum Bilgisi
                    if "status" in data and data["status"]:
                        match_obj["status"] = data["status"]
                        
                    # 2. Canlı Dakika Bilgisi (matchTime: ms)
                    if "matchTime" in data and data["matchTime"] is not None:
                        ms = data["matchTime"]
                        match_obj["match_time_ms"] = ms
                        total_secs = ms // 1000
                        mins = total_secs // 60
                        secs = total_secs % 60
                        match_obj["minute"] = f"{mins:02d}:{secs:02d} ({mins+1}')"
                        
                    # 3. Canlı Skor Bilgisi
                    if "matchScore" in data:
                        ms = data["matchScore"]
                        match_obj["score"] = f"{ms.get('t1', 0)} - {ms.get('t2', 0)}"
                        
                    # 4. Oran Grupları
                    odds_groups = data.get("oddsGroups", [])
                    for group in odds_groups:
                        gid = str(group.get("id", ""))
                        gname = (group.get("name") or "").strip()
                        
                        for odd in group.get("oddsList", []):
                            oid = odd.get("id")
                            cf = odd.get("cf")
                            if not oid or not cf:
                                continue
                                
                            # Yeni metadata geldiyse registry'ye kaydet
                            if gname or odd.get("name") or odd.get("outcome") or odd.get("vars"):
                                raw_outcome = str(odd.get("outcome") or odd.get("name", "")).strip().lower()
                                line = odd.get("vars", {}).get("v1")
                                if not line and odd.get("name"):
                                    parts = odd.get("name").split()
                                    if len(parts) > 1 and parts[-1].replace('.', '', 1).isdigit():
                                        line = parts[-1]
                                        
                                odds_meta_registry[oid] = {
                                    "gid": gid,
                                    "gname": gname,
                                    "outcome": raw_outcome,
                                    "line": line,
                                    "name": odd.get("name", "")
                                }
                                
                            meta = odds_meta_registry.get(oid, {})
                            cur_gname = meta.get("gname") or gname
                            cur_gid = meta.get("gid") or gid
                            cur_outcome = meta.get("outcome", "")
                            cur_line = meta.get("line")
                            odd_name = meta.get("name", "")
                            
                            # A) 1X2 (Normal Süre Sonucu)
                            if cur_gname == "Normal süre sonucu" or "maç sonucu" in cur_gname.lower() or cur_gid == "6257":
                                if cur_outcome in ["1", "x", "2"]:
                                    match_obj["odds_1x2"][cur_outcome.upper()] = cf
                                    
                            # B) Maç Toplam Gol (Alt / Üst)
                            elif cur_gname == "Toplam" or cur_gid in ["6379", "6271"] or cur_gname.startswith("Toplam"):
                                if cur_line:
                                    is_under = cur_outcome == "under" or "alt" in odd_name.lower()
                                    is_over = cur_outcome == "over" or "üst" in odd_name.lower() or "ust" in odd_name.lower()
                                    
                                    # Asya (çeyrekli baraj: .25, .75) çekilmez, filtrelenir
                                    try:
                                        f_line = float(cur_line)
                                        if (f_line * 4) % 2 != 0:  # 1.25, 1.75, 2.25 vb.
                                            continue
                                    except:
                                        pass
                                        
                                    if cur_line not in match_obj["odds_totals"]:
                                        match_obj["odds_totals"][cur_line] = {}
                                    if is_under:
                                        match_obj["odds_totals"][cur_line]["Alt"] = cf
                                    elif is_over:
                                        match_obj["odds_totals"][cur_line]["Üst"] = cf
                                        
                            # C) Ev Sahibi Toplam Gol (Alt / Üst)
                            elif cur_gid == "153087" or (match_obj["home"].lower() in cur_gname.lower() and "toplam" in cur_gname.lower()):
                                if cur_line:
                                    is_under = cur_outcome == "under" or "alt" in odd_name.lower()
                                    is_over = cur_outcome == "over" or "üst" in odd_name.lower()
                                    if cur_line not in match_obj["odds_home_totals"]:
                                        match_obj["odds_home_totals"][cur_line] = {}
                                    if is_under:
                                        match_obj["odds_home_totals"][cur_line]["Alt"] = cf
                                    elif is_over:
                                        match_obj["odds_home_totals"][cur_line]["Üst"] = cf
                                        
                            # D) Deplasman Toplam Gol (Alt / Üst)
                            elif cur_gid == "153088" or (match_obj["away"].lower() in cur_gname.lower() and "toplam" in cur_gname.lower()):
                                if cur_line:
                                    is_under = cur_outcome == "under" or "alt" in odd_name.lower()
                                    is_over = cur_outcome == "over" or "üst" in odd_name.lower()
                                    if cur_line not in match_obj["odds_away_totals"]:
                                        match_obj["odds_away_totals"][cur_line] = {}
                                    if is_under:
                                        match_obj["odds_away_totals"][cur_line]["Alt"] = cf
                                    elif is_over:
                                        match_obj["odds_away_totals"][cur_line]["Üst"] = cf
                                        
                            # E) İki Takım da Gol Atar (KG Var / Yok)
                            elif "iki takım da gol atar" in cur_gname.lower() or cur_gid == "6280":
                                if cur_outcome == "yes" or "evet" in odd_name.lower():
                                    match_obj["odds_btts"]["KG Var"] = cf
                                elif cur_outcome == "no" or "hayır" in odd_name.lower():
                                    match_obj["odds_btts"]["KG Yok"] = cf
                                    
                            match_obj["all_odds"][f"{cur_gname} | {odd_name}"] = cf
        except Exception:
            pass

def on_error(ws, error):
    pass

def on_close(ws, close_status_code, close_msg):
    pass

def on_open(ws):
    pass

ws = websocket.WebSocketApp(
    WS_URL,
    header=[f"{k}: {v}" for k, v in HEADERS.items()],
    on_open=on_open,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close
)

wst = threading.Thread(target=ws.run_forever)
wst.daemon = True
wst.start()

print("2. Canlı Oran Push Sunucusuna bağlanıldı (Tüm Alt/Üst ve Takım Gol Oranları toplanıyor, 6 saniye)...")
time.sleep(6)
ws.close()
sys.stdout.flush()

# 3. Canlı Tablo Çıktısı
print("\n" + "=" * 110)
print(f"{'CANLI FUTBOL: DAKİKA, MAÇ / EV / DEP ALT-ÜST ORANLARI (1WIN)':^110}")
print("=" * 110)

results_list = []

def format_totals_line(totals_dict):
    """Sıralı baraj listesi üretir: '2.5 [Alt: 1.85 / Üst: 1.95]'"""
    formatted = []
    for line in sorted(totals_dict.keys(), key=lambda x: float(x) if x.replace('.', '', 1).isdigit() else 99):
        alt = totals_dict[line].get("Alt", "-")
        ust = totals_dict[line].get("Üst", "-")
        formatted.append(f"{line} Gol [Alt: {alt} / Üst: {ust}]")
    return formatted

for mid, m in active_matches.items():
    o1 = m["odds_1x2"].get("1", "-")
    ox = m["odds_1x2"].get("X", "-")
    o2 = m["odds_1x2"].get("2", "-")
    
    time_display = m["status"]
    if m["minute"]:
        time_display = f"{m['status']} - {m['minute']}"
        
    print(f"[{time_display:<26}] {m['name']} ({m['tournament']})")
    print(f"   ⏱  Skor: {m['score']:<7} | 1 (Ev): {str(o1):<5} | X (Berabere): {str(ox):<5} | 2 (Dep): {str(o2):<5}")
    
    # 1. Standart Toplam Gol (0.5, 1.5, 2.0, 2.5, 3.5, 4.5 ...)
    std_totals = format_totals_line(m["odds_totals"])
    if std_totals:
        print(f"   ⚽ Maç Toplam:  {'  |  '.join(std_totals)}")
        
    # 3. Ev Sahibi Toplam Gol
    home_totals = format_totals_line(m["odds_home_totals"])
    if home_totals:
        print(f"   🏠 {m['home'][:16]} Toplam: {'  |  '.join(home_totals)}")
        
    # 4. Deplasman Toplam Gol
    away_totals = format_totals_line(m["odds_away_totals"])
    if away_totals:
        print(f"   ✈️  {m['away'][:16]} Toplam: {'  |  '.join(away_totals)}")
        
    # 5. KG Var / Yok
    if m["odds_btts"]:
        kg_v = m["odds_btts"].get("KG Var", "-")
        kg_y = m["odds_btts"].get("KG Yok", "-")
        print(f"   🎯 Karşılıklı Gol: Var: {kg_v}  |  Yok: {kg_y}")
        
    # 6. Canlı Yayın ve Canlı Takipçi Linkleri
    if m["broadcast"]:
        b_url = m["broadcast"].get("url")
        watch_url = f"http://localhost:{LOCAL_PLAYER_PORT}/watch?url={urllib.parse.quote(b_url)}"
        m["broadcast"]["watch_url"] = watch_url
        print(f"   📺 Canlı Yayın İzle: {watch_url}")
        print(f"   🔗 Ham Link:         {b_url}")
    if m["live_tracker"]:
        lt_url = m["live_tracker"].get("url")
        print(f"   📡 Maç Takipçisi:    {lt_url}")
        
    print("-" * 110)
    results_list.append(m)

# JSON Dosyasına Kaydet
with open("live_matches_with_odds.json", "w", encoding="utf-8") as f:
    json.dump(results_list, f, ensure_ascii=False, indent=2)

print(f"\nToplam {len(results_list)} maç 'live_matches_with_odds.json' dosyasına kaydedildi!")

if any(m.get("broadcast") for m in results_list):
    print(f"\n📺 CANLI YAYIN OYNATICI AÇIK: Yukarıdaki 'http://localhost:{LOCAL_PLAYER_PORT}/watch?...' linkine tıklayarak maçı direkt izleyebilirsiniz.")
    print("▶ Maçı tarayıcınızdan izleyebilmeniz için servis çalışıyor (Kapatmak için terminalde Ctrl+C yapabilirsiniz)...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nOynatıcı kapatıldı.")
