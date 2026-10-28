import os
import sys
import json
import time
import re
import urllib.parse
import threading
import requests
import websocket
from flask import Flask, render_template, jsonify, request, Response

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

# --- YAPILANDIRMA ---
PARTNER_ID = "44ba10e5-7df2-47ab-a44d-dc93803c7a6e"
REST_BASE = "https://api-gateway.top-parser.com"
WS_URL = f"wss://api-gateway.top-parser.com/push-server-v2/?Language=tr-TR&externalPartnerId={PARTNER_ID}&EIO=4&transport=websocket"

HEADERS = {
    "Origin": "https://1wtlrj.life",
    "Referer": "https://1wtlrj.life/",
    "x-external-partner-id": PARTNER_ID,
    "x-lang": "tr-TR",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

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

# --- GLOBAL MAÇ VERİ TABANI ---
matches_lock = threading.Lock()
active_matches = {}

def clean_league_name(slug_or_name):
    if not slug_or_name:
        return "Futbol Ligi"
    cleaned = str(slug_or_name).replace("-", " ").title()
    return cleaned

def fetch_rest_matches():
    """REST API'den canlı gerçek futbol maçlarını çeker."""
    try:
        r = requests.post(
            f"{REST_BASE}/matches/get-many",
            json={"sportId": 18, "isLive": True, "service": "LIVE", "limit": 100},
            params={"l": "tr-TR", "p": PARTNER_ID},
            headers=HEADERS,
            timeout=8
        )
        items = r.json().get("result", {}).get("items", [])
        new_ids = []
        with matches_lock:
            current_ids = set(active_matches.keys())
            seen_ids = set()
            for m in items:
                mid = m.get("id")
                if not mid or m.get("closed", False) or not is_real_football(m):
                    continue
                seen_ids.add(mid)
                home_obj = m.get("homeTeam", {})
                away_obj = m.get("awayTeam", {})
                home_name = home_obj.get("name", "Ev Sahibi")
                away_name = away_obj.get("name", "Deplasman")
                home_logo = home_obj.get("logo", {}).get("url") if isinstance(home_obj.get("logo"), dict) else None
                away_logo = away_obj.get("logo", {}).get("url") if isinstance(away_obj.get("logo"), dict) else None
                
                tour_slug = m.get("tournament", {}).get("slug", "")
                tour_name = m.get("tournament", {}).get("name") or clean_league_name(tour_slug)
                cat_slug = m.get("category", {}).get("slug", "")
                cat_name = m.get("category", {}).get("name") or clean_league_name(cat_slug)
                
                if mid not in active_matches:
                    active_matches[mid] = {
                        "id": mid,
                        "home": home_name,
                        "away": away_name,
                        "home_logo": home_logo,
                        "away_logo": away_logo,
                        "name": f"{home_name} vs {away_name}",
                        "tournament": tour_name,
                        "category": cat_name,
                        "status": "Canlı",
                        "minute": "",
                        "score": "0 - 0",
                        "broadcast": None
                    }
                else:
                    active_matches[mid]["home_logo"] = home_logo or active_matches[mid]["home_logo"]
                    active_matches[mid]["away_logo"] = away_logo or active_matches[mid]["away_logo"]
                    active_matches[mid]["tournament"] = tour_name
                    active_matches[mid]["category"] = cat_name
                    
                new_ids.append(mid)
                
            closed_ids = current_ids - seen_ids
            for cid in closed_ids:
                active_matches.pop(cid, None)
                
        return new_ids
    except Exception as e:
        print(f"REST Hata: {e}")
        return []

# --- WEBSOCKET YAYIN VE SKOR DİNLEYİCİSİ ---
class LiveWebSocketClient:
    def __init__(self):
        self.ws = None
        self.is_running = True
        self.subscribed_ids = set()

    def run(self):
        while self.is_running:
            try:
                self.ws = websocket.WebSocketApp(
                    WS_URL,
                    header=[f"{k}: {v}" for k, v in HEADERS.items()],
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                self.ws.run_forever(ping_interval=25, ping_timeout=10)
            except Exception:
                pass
            time.sleep(3)

    def on_open(self, ws):
        pass

    def on_message(self, ws, message):
        if message.startswith("0"):
            ws.send("40")
        elif message.startswith("40"):
            self.send_subscriptions(ws)
        elif message == "2":
            ws.send("3")
        elif message.startswith("42"):
            try:
                payload = json.loads(message[2:])
                if payload[0] == "u":
                    self.handle_update(payload[1].get("data", {}))
            except Exception:
                pass

    def on_error(self, ws, error):
        pass

    def on_close(self, ws, close_status_code, close_msg):
        self.subscribed_ids.clear()

    def send_subscriptions(self, ws=None):
        target_ws = ws or self.ws
        if not target_ws:
            return
        with matches_lock:
            mids = list(active_matches.keys())
        if not mids:
            return
            
        sub_info = {
            "messageType": "subscribe-match-info",
            "data": {"matchIds": mids}
        }
        try:
            target_ws.send(f'42{json.dumps(["subscribe", sub_info])}')
            self.subscribed_ids = set(mids)
        except Exception:
            pass

    def handle_update(self, data):
        mid = data.get("matchId")
        if not mid:
            return
            
        with matches_lock:
            if mid not in active_matches:
                return
            match_obj = active_matches[mid]
            
            # Canlı Yayın URL'si
            if "broadcast" in data and data["broadcast"]:
                match_obj["broadcast"] = data["broadcast"]
                
            # Devre & Süre
            if "status" in data and data["status"]:
                match_obj["status"] = data["status"]
            if "matchTime" in data and data["matchTime"] is not None:
                ms = data["matchTime"]
                total_secs = ms // 1000
                mins = total_secs // 60
                secs = total_secs % 60
                match_obj["minute"] = f"{mins:02d}:{secs:02d} ({mins+1}')"
                
            # Skor
            if "matchScore" in data:
                ms = data["matchScore"]
                match_obj["score"] = f"{ms.get('t1', 0)} - {ms.get('t2', 0)}"

ws_client = LiveWebSocketClient()

def background_sync_worker():
    print("-> Canlı maç ve yayın arama motoru devrede...")
    while True:
        try:
            mids = fetch_rest_matches()
            if ws_client.ws and ws_client.ws.sock and ws_client.ws.sock.connected:
                current_set = set(mids)
                if current_set != ws_client.subscribed_ids:
                    ws_client.send_subscriptions()
        except Exception:
            pass
        time.sleep(20)

threading.Thread(target=ws_client.run, daemon=True).start()
threading.Thread(target=background_sync_worker, daemon=True).start()

# --- FLASK WEB UYGULAMASI ---
app = Flask(__name__, template_folder="templates")
app.config['TEMPLATES_AUTO_RELOAD'] = True

@app.after_request
def enable_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/matches")
def get_matches():
    with matches_lock:
        # SADECE CANLI VİDEO YAYINI OLAN MAÇLARI AL
        streamable_matches = [
            m for m in active_matches.values()
            if m.get("broadcast") and m.get("broadcast", {}).get("url")
        ]
        
    return jsonify({
        "status": "success",
        "total": len(streamable_matches),
        "matches": streamable_matches
    })

@app.route("/player/stream")
def player_stream():
    """
    Yayın URL'sini çeker, 'muted' etiketini kaldırır ve sesi otomatik açık başlatır.
    Anti-hotlink (Referer) korumasını da backend üzerinde çözer.
    """
    raw_url = request.args.get("url", "")
    if not raw_url:
        return "Yayın URL'si belirtilmedi.", 400
        
    decoded_url = urllib.parse.unquote(raw_url)
    
    try:
        res = requests.get(
            decoded_url,
            headers={
                "Referer": "https://1wtlrj.life/",
                "Origin": "https://1wtlrj.life",
                "User-Agent": HEADERS["User-Agent"]
            },
            timeout=5
        )
        if res.status_code == 200:
            content = res.text
            # 1. Video etiketinden 'muted' niteliğini kaldır ve mobilde tam ekranı zorlamaması için playsinline ekle
            content = re.sub(r'\bcontrols\s+muted\b', 'controls', content)
            content = re.sub(r'\bmuted\b', '', content)
            if "<video" in content:
                content = content.replace("<video", '<video playsinline="true" webkit-playsinline="true" x5-playsinline="true" ')
            
            # 2. Base tag ve sesi zorla açan betiği ekle
            parsed = urllib.parse.urlparse(decoded_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            
            unmute_script = """
            <script>
            function forceUnmute() {
                var v = document.getElementById('video');
                if (v) {
                    v.muted = false;
                    v.defaultMuted = false;
                    v.volume = 1.0;
                    if (v.paused) {
                        var p = v.play();
                        if (p !== undefined) {
                            p.catch(function() {
                                v.muted = true;
                                v.play();
                            });
                        }
                    }
                }
            }
            window.addEventListener('message', function(e) {
                if (e.data === 'unmute') { forceUnmute(); }
            });
            document.addEventListener('DOMContentLoaded', forceUnmute);
            window.addEventListener('load', forceUnmute);
            document.addEventListener('click', forceUnmute);
            document.addEventListener('touchstart', forceUnmute, { passive: true });
            document.addEventListener('touchend', forceUnmute, { passive: true });
            </script>
            """
            
            if "<head>" in content:
                content = content.replace("<head>", f'<head><base href="{base_url}">{unmute_script}')
            elif "<html>" in content:
                content = content.replace("<html>", f'<html><head><base href="{base_url}">{unmute_script}</head>')
            else:
                content = f'<base href="{base_url}">{unmute_script}' + content
                
            return Response(content, mimetype="text/html; charset=utf-8")
    except Exception as e:
        pass
        
    # Fallback iframe
    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="referrer" content="always">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Canlı Oynatıcı</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ width: 100%; height: 100%; background: #000; overflow: hidden; }}
        iframe {{ width: 100%; height: 100%; border: 0; display: block; }}
    </style>
</head>
<body>
    <iframe src="{decoded_url}" allow="autoplay *; fullscreen *; encrypted-media *" allowfullscreen></iframe>
</body>
</html>"""
    return Response(html, mimetype="text/html; charset=utf-8")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("\n" + "=" * 70)
    print("📺 CANLI FUTBOL TV BAŞLATILDI (SADECE YAYINLI MAÇLAR)")
    print(f"👉 Port: {port}")
    print("=" * 70 + "\n")
    
    try:
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    except Exception:
        pass
        
    app.run(host="0.0.0.0", port=port, debug=False)
