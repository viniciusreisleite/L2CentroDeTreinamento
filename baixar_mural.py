# -*- coding: utf-8 -*-
import os
import sys
import glob
import json
import time
import urllib.request
import yt_dlp
from playwright.sync_api import sync_playwright

PERFIS = [
    {"username": "loja_somzao", "badge": "LOJA SOMZÃO", "color": "#ff1744"},
    {"username": "estetica_somzao", "badge": "ESTÉTICA AUTOMOTIVA", "color": "#00e5ff"}
]
TARGET_POR_PERFIL = 6

def progresso_hook(d):
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        baixado = d.get('downloaded_bytes', 0)
        velocidade = d.get('speed') or 0
        b_mb = baixado / (1024 * 1024)
        vel = (velocidade / (1024 * 1024)) if velocidade else 0
        
        largura_barra = 25
        if total > 0:
            pct = (baixado / total) * 100
            t_mb = total / (1024 * 1024)
            preenchido = int(largura_barra * baixado // total)
            barra = '█' * preenchido + '░' * (largura_barra - preenchido)
            sys.stdout.write(f"\r  [{barra}] {pct:5.1f}% | {b_mb:5.2f} MB / {t_mb:5.2f} MB | {vel:5.2f} MB/s")
        else:
            frames = ['-', '\\', '|', '/']
            frame = frames[int(time.time() * 4) % len(frames)]
            sys.stdout.write(f"\r  [{frame}] Baixando... | {b_mb:5.2f} MB baixados | {vel:5.2f} MB/s")
        sys.stdout.flush()
    elif d['status'] == 'finished':
        fn = d.get('filename')
        t_mb = (os.path.getsize(fn) / (1024 * 1024)) if fn and os.path.exists(fn) else ((d.get('total_bytes', 0)) / (1024 * 1024))
        barra_cheia = '█' * 25
        print(f"\r  [{barra_cheia}] 100.0% | Concluido! Tamanho: {t_mb:.2f} MB" + " " * 15)

def cleanup_old_media(allowed_files):
    for file_path in glob.glob("media_*.*") + glob.glob("video_*.mp4"):
        if file_path not in allowed_files:
            try:
                os.remove(file_path)
            except Exception:
                pass

def carregar_cookies_locais():
    playwright_cookies = []
    cookie_file = "cookies.txt"
    if not os.path.exists(cookie_file):
        return playwright_cookies

    with open(cookie_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                domain, _, path, secure, expires, name, value = parts[:7]
                playwright_cookies.append({
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": path,
                    "secure": secure.lower() == "true",
                    "expires": float(expires) if expires.isdigit() else -1
                })
    return playwright_cookies

def main():
    cookie_file = "cookies.txt" if os.path.exists("cookies.txt") else None
    playwright_cookies = carregar_cookies_locais()

    coletados_por_perfil = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )

        if playwright_cookies:
            context.add_cookies(playwright_cookies)

        page = context.new_page()

        for config in PERFIS:
            usr = config["username"]
            posts_urls = []
            print(f"\nAcessando feed de @{usr}...")

            try:
                page.goto(f"https://www.instagram.com/{usr}/", wait_until="domcontentloaded", timeout=60000)
                time.sleep(4)

                for scroll_step in range(6):
                    raw_items = page.evaluate("""() => {
                        const links = Array.from(document.querySelectorAll("a[href*='/p/'], a[href*='/reel/']"));
                        return links.map(el => {
                            const rect = el.getBoundingClientRect();
                            const isPinned = !!el.querySelector("svg[aria-label*='Pin'], svg[aria-label*='Fixado']");
                            return {
                                href: el.getAttribute('href'),
                                top: rect.top + window.scrollY,
                                left: rect.left,
                                isPinned: isPinned
                            };
                        });
                    }""")

                    raw_items.sort(key=lambda x: (x['top'], x['left']))

                    for item in raw_items:
                        if item.get("isPinned"):
                            continue
                        href = item.get("href")
                        if href:
                            full_url = f"https://www.instagram.com{href}" if href.startswith("/") else href
                            clean_url = full_url.split("?")[0]
                            if clean_url not in posts_urls:
                                posts_urls.append(clean_url)

                    if len(posts_urls) >= TARGET_POR_PERFIL:
                        break

                    page.mouse.wheel(0, 800)
                    time.sleep(2)

            except Exception as e:
                print(f"Aviso ao coletar @{usr}: {e}")

            coletados_por_perfil[usr] = posts_urls[:TARGET_POR_PERFIL]
            print(f"Posts identificados em @{usr}: {len(coletados_por_perfil[usr])}")

        # Intercala os posts dos dois perfis
        fila_unificada = []
        max_len = max(len(coletados_por_perfil.get(c["username"], [])) for c in PERFIS)
        for i in range(max_len):
            for c in PERFIS:
                lista = coletados_por_perfil.get(c["username"], [])
                if i < len(lista):
                    fila_unificada.append({
                        "url": lista[i],
                        "perfil": c["username"],
                        "badge": c["badge"],
                        "color": c["color"]
                    })

        posts_data = []
        allowed_files = []

        for idx, item in enumerate(fila_unificada, start=1):
            post_url = item["url"]
            print(f"\n[{idx}/{len(fila_unificada)}] Processando (@{item['perfil']}): {post_url}")
            is_video = "/reel/" in post_url
            slide_index = 1
            caption = ""
            image_download_url = ""

            try:
                page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)

                try:
                    meta_desc = page.locator('meta[property="og:description"]').get_attribute("content")
                    if meta_desc:
                        if '": "' in meta_desc:
                            caption = meta_desc.split('": "', 1)[1].rstrip('"')
                        elif ': "' in meta_desc:
                            caption = meta_desc.split(': "', 1)[1].rstrip('"')
                        else:
                            caption = meta_desc
                except Exception:
                    pass

                if not caption:
                    caption_elem = page.query_selector("article h1, h1, div[class*='_a9zs'], span[class*='_aacl']")
                    if caption_elem:
                        caption = caption_elem.inner_text().strip()

                if not caption:
                    img_com_alt = page.query_selector("article img[alt]")
                    if img_com_alt:
                        alt_txt = img_com_alt.get_attribute("alt") or ""
                        if "Foto de" in alt_txt or "Photo by" in alt_txt:
                            caption = alt_txt

                # 1. Deteccao por Meta Tags (servidor/SSR)
                try:
                    og_type = page.locator('meta[property="og:type"]').get_attribute("content") or ""
                    og_video = page.locator('meta[property="og:video"]').get_attribute("content") or ""
                    if "video" in og_type.lower() or bool(og_video):
                        is_video = True
                except Exception:
                    pass

                # 2. Deteccao por Elemento no DOM
                if not is_video:
                    if page.query_selector("video, article video, div[role='dialog'] video"):
                        is_video = True

                if not is_video:
                    try:
                        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl_chk:
                            info_chk = ydl_chk.extract_info(post_url, download=False)
                            entries_chk = info_chk.get("entries", [])
                            if entries_chk:
                                for num_s, slide_s in enumerate(entries_chk, start=1):
                                    vcodec_s = slide_s.get("vcodec")
                                    ext_s = slide_s.get("ext")
                                    if (vcodec_s and vcodec_s != "none") or ext_s == "mp4":
                                        is_video = True
                                        slide_index = num_s
                                        break
                            elif (info_chk.get("vcodec") and info_chk.get("vcodec") != "none") or info_chk.get("ext") == "mp4":
                                is_video = True
                    except Exception:
                        pass

                if not is_video:
                    img_elem = page.query_selector("article img, div[role='dialog'] img, img[style*='object-fit']")
                    if img_elem:
                        srcset = img_elem.get_attribute("srcset")
                        if srcset:
                            candidatos = []
                            for p_part in srcset.split(","):
                                partes = p_part.strip().split(" ")
                                if len(partes) == 2:
                                    w = int(partes[1].replace("w", ""))
                                    candidatos.append((w, partes[0]))
                            if candidatos:
                                candidatos.sort(key=lambda x: x[0], reverse=True)
                                image_download_url = candidatos[0][1]

                        if not image_download_url:
                            image_download_url = img_elem.get_attribute("src") or ""

            except Exception as e:
                print(f"Aviso no post #{idx}: {e}")

            if is_video:
                output_filename = f"media_{idx}.mp4"
                allowed_files.append(output_filename)

                opts_video = {
                    'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                    'outtmpl': output_filename,
                    'playlist_items': str(slide_index),
                    'overwrites': True,
                    'cookiefile': cookie_file,
                    'progress_hooks': [progresso_hook],
                    'quiet': False,
                    'noprogress': True,
                    'no_warnings': True,
                    'postprocessor_args': [
                        '-c:v', 'libx264',
                        '-crf', '17',
                        '-preset', 'fast',
                        '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac',
                        '-b:a', '192k',
                        '-movflags', '+faststart'
                    ]
                }

                sucesso_video = False
                try:
                    with yt_dlp.YoutubeDL(opts_video) as ydl:
                        ydl.download([post_url])
                    if os.path.exists(output_filename) and os.path.getsize(output_filename) > 1000:
                        sucesso_video = True
                except Exception as e:
                    print(f"Aviso download de video: {e}")

                if sucesso_video:
                    posts_data.append({
                        "id": idx,
                        "perfil": item["perfil"],
                        "badge": item["badge"],
                        "badge_color": item["color"],
                        "type": "video",
                        "url": post_url,
                        "media": output_filename,
                        "media_file": output_filename,
                        "video_file": output_filename,
                        "caption": caption,
                        "updated_at": time.strftime("%d/%m/%Y as %H:%M")
                    })
                    print(f"Salvo (video): {output_filename} | @{item['perfil']}")
                else:
                    if os.path.exists(output_filename):
                        try: os.remove(output_filename)
                        except Exception: pass
                    allowed_files.remove(output_filename)
                    output_filename = f"media_{idx}.jpg"
                    allowed_files.append(output_filename)

                    baixou = False
                    if image_download_url:
                        try:
                            req = urllib.request.Request(image_download_url, headers={'User-Agent': 'Mozilla/5.0'})
                            with urllib.request.urlopen(req, timeout=20) as resp, open(output_filename, 'wb') as out_f:
                                out_f.write(resp.read())
                            baixou = True
                        except Exception: pass

                    if not baixou:
                        try:
                            node = page.query_selector("article img, div[role='dialog'] img")
                            if node:
                                node.screenshot(path=output_filename)
                                baixou = True
                        except Exception: pass

                    posts_data.append({
                        "id": idx,
                        "perfil": item["perfil"],
                        "badge": item["badge"],
                        "badge_color": item["color"],
                        "type": "image",
                        "url": post_url,
                        "media": output_filename,
                        "media_file": output_filename,
                        "video_file": output_filename,
                        "caption": caption,
                        "updated_at": time.strftime("%d/%m/%Y as %H:%M")
                    })
                    print(f"Salvo (foto fallback): {output_filename} | @{item['perfil']}")

            else:
                output_filename = f"media_{idx}.jpg"
                allowed_files.append(output_filename)

                baixou = False
                if image_download_url:
                    try:
                        req = urllib.request.Request(image_download_url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req, timeout=20) as resp, open(output_filename, 'wb') as out_f:
                            out_f.write(resp.read())
                        baixou = True
                    except Exception as e:
                        print(f"Erro ao baixar imagem: {e}")

                if not baixou:
                    try:
                        node = page.query_selector("article img, div[role='dialog'] img")
                        if node:
                            node.screenshot(path=output_filename)
                            baixou = True
                    except Exception: pass

                posts_data.append({
                    "id": idx,
                    "perfil": item["perfil"],
                    "badge": item["badge"],
                    "badge_color": item["color"],
                    "type": "image",
                    "url": post_url,
                    "media": output_filename,
                    "media_file": output_filename,
                    "video_file": output_filename,
                    "caption": caption,
                    "updated_at": time.strftime("%d/%m/%Y as %H:%M")
                })
                print(f"Salvo (foto): {output_filename} | @{item['perfil']}")

        browser.close()

    cleanup_old_media(allowed_files)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(posts_data, f, ensure_ascii=False, indent=2)

    print("\nConcluido! data.json atualizado com os dois perfis integrados.")

if __name__ == "__main__":
    main()