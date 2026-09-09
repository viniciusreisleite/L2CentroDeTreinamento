import os
import sys
import time
import json
import requests
from playwright.sync_api import sync_playwright

PERFIL = "l2_centrodetreinamento"
BADGE_TEXTO = "L2 Centro de Treinamento"
COR_TEMA = "#f97316"
TOTAL_MIDIAS = 12
COOKIES_FILE = "cookies.txt"

def carregar_cookies():
    cookies_dict = {}
    if os.path.exists(COOKIES_FILE):
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"): continue
                p = line.split("\t")
                if len(p) >= 7:
                    cookies_dict[p[5]] = p[6]
    return cookies_dict

def shortcode_to_media_id(shortcode):
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    media_id = 0
    for letter in shortcode:
        media_id = (media_id * 64) + alphabet.index(letter)
    return str(media_id)

def baixar_midia_por_tipo(shortcode, out_prefix, cookies_dict):
    """
    Identifica na API do Instagram se o post é Vídeo, Imagem Única ou Carrossel
    e faz o download exato na resolução máxima nativa sem cortes.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "Accept": "*/*"
    }
    
    mid = shortcode_to_media_id(shortcode)
    api_url = f"https://www.instagram.com/api/v1/media/{mid}/info/"
    
    try:
        r = requests.get(api_url, headers=headers, cookies=cookies_dict, timeout=15)
        if r.status_code != 200:
            print(f"      [ERRO HTTP {r.status_code}] Falha ao consultar metadados do post.")
            return None, None
            
        data = r.json()
        items = data.get("items", [])
        if not items:
            return None, None
            
        item = items[0]
        media_type = item.get("media_type") # 1: Foto, 2: Vídeo, 8: Carrossel
        
        # Caso seja Carrossel, pegamos o primeiro slide
        if media_type == 8:
            carousel = item.get("carousel_media", [])
            if not carousel:
                return None, None
            item = carousel[0]
            media_type = item.get("media_type")
            print(f"      -> Detectado: CARROSSEL (extraindo slide 1)")

        # 1. Post é VÍDEO
        if media_type == 2:
            videos = item.get("video_versions", [])
            if videos:
                video_url = videos[0]["url"]
                arquivo = f"{out_prefix}.mp4"
                print(f"      -> Detectado: VIDEO ({videos[0].get('width')}x{videos[0].get('height')})")
                res = requests.get(video_url, timeout=30)
                if res.status_code == 200:
                    with open(arquivo, "wb") as f:
                        f.write(res.content)
                    return "video", arquivo

        # 2. Post é IMAGEM
        elif media_type == 1:
            candidatos = item.get("image_versions2", {}).get("candidates", [])
            if candidatos:
                img_url = candidatos[0]["url"]
                arquivo = f"{out_prefix}.jpg"
                print(f"      -> Detectado: IMAGEM ({candidatos[0].get('width')}x{candidatos[0].get('height')} - Proporção Integral)")
                res = requests.get(img_url, timeout=20)
                if res.status_code == 200:
                    with open(arquivo, "wb") as f:
                        f.write(res.content)
                    return "image", arquivo

    except Exception as e:
        print(f"      [EXCECAO API] {e}")

    return None, None

def main():
    print("=== SINCRONIZACAO ESTRUTURADA POR TIPO DE MIDIA ===")
    cookies_dict = carregar_cookies()
    
    cookies_playwright = []
    for k, v in cookies_dict.items():
        cookies_playwright.append({
            "name": k, "value": v, "domain": ".instagram.com", "path": "/"
        })

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        if cookies_playwright:
            ctx.add_cookies(cookies_playwright)
            
        page = ctx.new_page()
        print(f"\nChecando feed de @{PERFIL}...")
        page.goto(f"https://www.instagram.com/{PERFIL}/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        
        urls = []
        for _ in range(25):
            anchors = page.query_selector_all('a[href*="/p/"], a[href*="/reel/"]')
            for a in anchors:
                h = a.get_attribute("href")
                if h:
                    clean = "https://www.instagram.com/" + h.split("?")[0].strip("/") + "/"
                    if clean not in urls:
                        urls.append(clean)
            if len(urls) >= TOTAL_MIDIAS:
                break
            page.evaluate("window.scrollBy(0, 1500)")
            page.wait_for_timeout(1000)
        
        # urls completo para fallback
        print(f"Posts no feed: {len(urls)} identificados.")
        
        posts_a_manter = []
        
        for url in urls:
            raw_sc = url.strip("/").split("/")[-1]; sc = raw_sc[:11] if len(raw_sc) > 11 and "_" not in raw_sc else raw_sc
            out_prefix = f"temp_{sc}"
            print(f"  [PROCESSANDO] {url}")
            
            caption = ""
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1000)
                meta_tag = page.query_selector('meta[property="og:title"]')
                if meta_tag:
                    caption = meta_tag.get_attribute("content") or ""
            except Exception:
                pass

            # Classifica o tipo e baixa o arquivo correspondente
            tipo_detectado, arquivo_gerado = baixar_midia_por_tipo(sc, out_prefix, cookies_dict)
            
            if arquivo_gerado and os.path.exists(arquivo_gerado):
                if len(posts_a_manter) >= TOTAL_MIDIAS: break
                posts_a_manter.append({
                    "id": sc,
                    "url": url,
                    "caption": caption,
                    "tipo": tipo_detectado,
                    "arquivo": arquivo_gerado,
                    "media": arquivo_gerado,
                    "media_file": arquivo_gerado,
                    "video_file": arquivo_gerado,
                    "imagem": arquivo_gerado,
                    "badge": BADGE_TEXTO,
                    "cor": COR_TEMA,
                    "perfil": PERFIL
                })
        
        browser.close()

    if len(posts_a_manter) < 6:
        print(f"\n[SEGURANCA] Apenas {len(posts_a_manter)} midias coletadas. Mantendo arquivos atuais.")
        return

    print("\nOrganizando arquivos de 1 a 12...")
    json_final = []
    
    for idx, post in enumerate(posts_a_manter, 1):
        ext = os.path.splitext(post["arquivo"])[1]
        nome_definitivo = f"media_{idx}{ext}"
        
        if os.path.exists(post["arquivo"]):
            if os.path.exists(nome_definitivo) and nome_definitivo != post["arquivo"]:
                try:
                    os.remove(nome_definitivo)
                except Exception:
                    pass
            try:
                os.rename(post["arquivo"], nome_definitivo)
            except Exception:
                pass
        
        post["arquivo"] = nome_definitivo
        post["media"] = nome_definitivo
        post["media_file"] = nome_definitivo
        post["video_file"] = nome_definitivo
        post["imagem"] = nome_definitivo
        json_final.append(post)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(json_final, f, indent=2, ensure_ascii=False)
        
    print(f"Concluido! {len(json_final)} midias identificadas e salvas com sucesso.")

if __name__ == "__main__":
    main()