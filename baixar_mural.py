# -*- coding: utf-8 -*-
import os
import sys
import glob
import json
import time
import urllib.request
import yt_dlp
from playwright.sync_api import sync_playwright

USERNAME = "l2_centrodetreinamento"
TARGET_COUNT = 12

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

    posts_urls = []

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
        print(f"Acessando feed de @{USERNAME}...")

        try:
            page.goto(f"https://www.instagram.com/{USERNAME}/", wait_until="domcontentloaded", timeout=60000)
            time.sleep(4)

            for scroll_step in range(6):
                raw_items = page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll("a[href*='/p/'], a[href*='/reel/']"));
                    return links.map(el => {
                        const rect = el.getBoundingClientRect();
                        const isPinned = !!el.querySelector("svg[aria-label*='Pin'], svg[aria-label*='Fixado'], svg[title*='Pin'], svg[title*='Fixado']");
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

                if len(posts_urls) >= TARGET_COUNT:
                    break

                page.mouse.wheel(0, 800)
                time.sleep(2)

        except Exception as e:
            print(f"Aviso durante navegacao inicial: {e}")

        posts_urls = posts_urls[:TARGET_COUNT]
        print(f"Total de posts cronologicos identificados: {len(posts_urls)}")

        if not posts_urls:
            print("Nenhum post foi identificado.")
            browser.close()
            return

        posts_data = []
        allowed_files = []

        for idx, post_url in enumerate(posts_urls, start=1):
            print(f"\n[{idx}/{len(posts_urls)}] Processando: {post_url}")
            is_video = "/reel/" in post_url
            caption = ""
            image_download_url = ""

            try:
                page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)

                # 1. Tenta pegar a legenda via meta tag og:description (mais estavel)
                try:
                    meta_desc = page.locator('meta[property="og:description"]').get_attribute("content")
                    if meta_desc:
                        # O Instagram formata como: "179 likes, 17 comments - Perfil on Date: "Texto da legenda""
                        if '": "' in meta_desc:
                            caption = meta_desc.split('": "', 1)[1].rstrip('"')
                        elif ': "' in meta_desc:
                            caption = meta_desc.split(': "', 1)[1].rstrip('"')
                        else:
                            caption = meta_desc
                except Exception:
                    pass

                # 2. Fallback: pega o texto dentro do post via DOM
                if not caption:
                    caption_elem = page.query_selector("article h1, h1, div[class*='_a9zs'], span[class*='_aacl']")
                    if caption_elem:
                        caption = caption_elem.inner_text().strip()

                # 3. Fallback: pega o atributo alt da imagem
                if not caption:
                    img_com_alt = page.query_selector("article img[alt]")
                    if img_com_alt:
                        alt_txt = img_com_alt.get_attribute("alt") or ""
                        if "Foto de" in alt_txt or "Photo by" in alt_txt:
                            caption = alt_txt

                video_elem = page.query_selector("video")
                if video_elem:
                    is_video = True
                elif not is_video:
                    img_elem = page.query_selector("article img, div[role='dialog'] img, img[style*='object-fit']")
                    if img_elem:
                        srcset = img_elem.get_attribute("srcset")
                        if srcset:
                            candidatos = []
                            for item in srcset.split(","):
                                partes = item.strip().split(" ")
                                if len(partes) == 2:
                                    w = int(partes[1].replace("w", ""))
                                    candidatos.append((w, partes[0]))
                            if candidatos:
                                candidatos.sort(key=lambda x: x[0], reverse=True)
                                image_download_url = candidatos[0][1]

                        if not image_download_url:
                            image_download_url = img_elem.get_attribute("src") or ""

            except Exception as e:
                print(f"Aviso ao inspecionar post #{idx}: {e}")

            if is_video:
                output_filename = f"media_{idx}.mp4"
                allowed_files.append(output_filename)

                opts_video = {
                    'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                    'outtmpl': output_filename,
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

                video_sucesso = False
                try:
                    with yt_dlp.YoutubeDL(opts_video) as ydl:
                        ydl.download([post_url])
                    if os.path.exists(output_filename) and os.path.getsize(output_filename) > 1000:
                        video_sucesso = True
                except Exception as e:
                    print(f"Aviso: nao e video unico ({e}). Alternando para foto...")

                if video_sucesso:
                    posts_data.append({
                        "id": idx,
                        "type": "video",
                        "url": post_url,
                        "media": output_filename,
                        "media_file": output_filename,
                        "video_file": output_filename,
                        "caption": caption,
                        "updated_at": time.strftime("%d/%m/%Y as %H:%M")
                    })
                    print(f"Salvo (video): {output_filename} | Legenda: {caption[:30]}...")
                else:
                    # Fallback imediato para imagem/carrossel
                    output_img = f"media_{idx}.jpg"
                    if output_filename in allowed_files:
                        allowed_files.remove(output_filename)
                    allowed_files.append(output_img)
                    downloaded = False
                    if image_download_url:
                        try:
                            req = urllib.request.Request(image_download_url, headers={'User-Agent': 'Mozilla/5.0'})
                            with urllib.request.urlopen(req, timeout=20) as response, open(output_img, 'wb') as out_f:
                                out_f.write(response.read())
                            downloaded = True
                        except Exception:
                            pass
                    if not downloaded:
                        try:
                            img_n = page.query_selector("article img, img[style*='object-fit']")
                            if img_n:
                                img_n.screenshot(path=output_img)
                                downloaded = True
                        except Exception:
                            pass
                    posts_data.append({
                        "id": idx,
                        "type": "image",
                        "url": post_url,
                        "media": output_img,
                        "media_file": output_img,
                        "image_file": output_img,
                        "caption": caption,
                        "updated_at": time.strftime("%d/%m/%Y as %H:%M")
                    })
                    print(f"Salvo (imagem fallback): {output_img} | Legenda: {caption[:30]}...")

            else:
                output_filename = f"media_{idx}.jpg"
                allowed_files.append(output_filename)

                downloaded = False
                if image_download_url:
                    try:
                        req = urllib.request.Request(image_download_url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req, timeout=20) as response, open(output_filename, 'wb') as out_file:
                            out_file.write(response.read())
                        downloaded = True
                    except Exception as e:
                        print(f"Erro ao baixar imagem: {e}")

                if not downloaded:
                    try:
                        img_node = page.query_selector("article img, img[style*='object-fit']")
                        if img_node:
                            img_node.screenshot(path=output_filename)
                            downloaded = True
                    except Exception:
                        pass

                posts_data.append({
                    "id": idx,
                    "type": "image",
                    "url": post_url,
                    "media": output_filename,
                    "media_file": output_filename,
                    "video_file": output_filename,
                    "caption": caption,
                    "updated_at": time.strftime("%d/%m/%Y as %H:%M")
                })
                print(f"Salvo (foto): {output_filename} | Legenda: {caption[:30]}...")

        browser.close()

    cleanup_old_media(allowed_files)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(posts_data, f, ensure_ascii=False, indent=2)

    print("\nConcluido! data.json atualizado com legendas completas.")

if __name__ == "__main__":
    main()