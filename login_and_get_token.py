import time
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

def capture_token_interactive():
    print("Chrome tarayıcısı bot koruması engellenerek açılıyor...")
    options = Options()
    # Ekranda görünür pencere olarak açıyoruz (headless DEĞİL)
    options.add_argument('--window-size=1280,800')
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    # Cloudflare / Bulmaca (Captcha) bot tespitini kapatma ayarları:
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    
    # navigator.webdriver = undefined yaparak bot tespitini tamamen kaldırıyoruz
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        '''
    })
    
    driver.get("https://1wtlrj.life/?p=w0xm")
    
    print("\n" + "="*60)
    print("Lütfen açılan tarayıcı penceresinde 1win hesabınıza GİRİŞ YAPIN.")
    print("Giriş yaptığınız anda token otomatik olarak yakalanacaktır...")
    print("="*60 + "\n")
    
    found_token = None
    start_time = time.time()
    
    # 2 dakika boyunca giriş yapılmasını ve token'ın düşmesini bekle
    while time.time() - start_time < 120:
        # 1. Performance loglarından kontrol et (Request headers)
        try:
            logs = driver.get_log('performance')
            for entry in logs:
                msg = json.loads(entry['message'])['message']
                if msg['method'] == 'Network.requestWillBeSent':
                    headers = msg['params']['request'].get('headers', {})
                    for h_name, h_val in headers.items():
                        if h_name.lower() == 'token' and len(h_val) > 20:
                            found_token = h_val
                            break
                        if h_name.lower() == 'authorization' and 'bearer' in h_val.lower():
                            found_token = h_val.split()[-1]
                            break
                if found_token:
                    break
        except Exception:
            pass
            
        if found_token:
            break
            
        # 2. LocalStorage ve Cookies üzerinden kontrol et
        try:
            storage_keys = driver.execute_script("return Object.keys(localStorage);")
            for k in storage_keys:
                if any(x in k.lower() for x in ['token', 'auth', 'session']):
                    val = driver.execute_script(f"return localStorage.getItem('{k}');")
                    if val and len(val) > 20:
                        found_token = val
                        break
        except Exception:
            pass
            
        if found_token:
            break
            
        time.sleep(2)
        
    if found_token:
        print(f"\nTEBRİKLER! Token başarıyla yakalandı: {found_token[:15]}...{found_token[-10:]}")
        # live_football_odds_tracker.py dosyasına kaydet
        with open("live_football_odds_tracker.py", "r", encoding="utf-8") as f:
            content = f.read()
            
        import re
        content = re.sub(
            r'USER_TOKEN = os\.environ\.get\("WIN1_TOKEN", ".*?"\)',
            f'USER_TOKEN = os.environ.get("WIN1_TOKEN", "{found_token}")',
            content
        )
        content = re.sub(
            r'USER_TOKEN = ".*?"',
            f'USER_TOKEN = "{found_token}"',
            content
        )
        
        with open("live_football_odds_tracker.py", "w", encoding="utf-8") as f:
            f.write(content)
            
        print("Token 'live_football_odds_tracker.py' dosyasına otomatik kaydedildi!")
    else:
        print("\nSüre doldu veya token henüz yakalanamadı.")
        
    driver.quit()
    return found_token

if __name__ == "__main__":
    capture_token_interactive()
