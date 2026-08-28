import os
import glob
import json
import subprocess
import time
from playwright.sync_api import sync_playwright

def cleanup_old_videos(allowed_files):
    """Deleta qualquer arquivo de vídeo que não esteja na lista dos 8 permitidos"""
    for file_path in glob.glob("*.mp4"):
        if file_path not in allowed_files:
            try:
                os.remove(file_path)
                print(f"🗑️ Arquivo antigo removido: {file_path}")
            except Exception as e:
                print(f"Erro ao remover {file_path}: {e}")

def main():
    cookies_raw = os.environ.get("INSTAGRAM_COOKIES", "")
    cookie_file = "cookies.txt"
    with open(cookie_file, "w", encoding="utf-8") as f:
        f.write(cookies_raw)

    playwright_cookies = []
    for line in cookies_raw.splitlines():
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

    username = "l2_centrodetreinamento"
    target_count = 8
    reels_urls = []

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
        print(f"Acessando perfil de @{username}...")

        target_urls = [
            f"https://www.instagram.com/{username}/reels/",
            f"https://www.instagram.com/{username}/"
        ]

        for target_url in target_urls:
            try:
                print(f"Tentando URL: {target_url}")
                page.goto(target_url, wait_until="networkidle", timeout=60000)
                time.sleep(6)

                for _ in range(5):
                    page.mouse.wheel(0, 800)
                    time.sleep(2)

                elements = page.query_selector_all("a[href*='/reel/'], a[href*='/p/']")
                for el in elements:
                    href = el.get_attribute("href")
                    if href:
                        full_url = f"https://www.instagram.com{href}" if href.startswith("/") else href
                        clean_url = full_url.split("?")[0]
                        if clean_url not in reels_urls:
                            reels_urls.append(clean_url)
                    if len(reels_urls) >= target_count:
                        break

                if len(reels_urls) >= target_count:
                    break

            except Exception as e:
                print(f"Aviso durante navegação em {target_url}: {e}")

        browser.close()

    print(f"\nTotal de posts localizados: {len(reels_urls)}")
    
    # Fallback caso necessário
    if not reels_urls:
        print("Tentando extração direta via yt-dlp flat-playlist...")
        try:
            cmd = [
                "yt-dlp",
                "--cookies", cookie_file,
                "--flat-playlist",
                "--print", "url",
                f"https://www.instagram.com/{username}/reels/"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.stdout:
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if line and line not in reels_urls:
                        reels_urls.append(line)
                    if len(reels_urls) >= target_count:
                        break
        except Exception as e:
            print(f"Erro no fallback yt-dlp: {e}")

    if not reels_urls:
        print("❌ Nenhum post foi identificado.")
        return

    # Baixa os vídeos e metadados
    posts_data = []
    allowed_videos = [f"video_{i}.mp4" for i in range(1, len(reels_urls[:target_count]) + 1)]

    for idx, reel_url in enumerate(reels_urls[:target_count], start=1):
        print(f"\n--- Processando Post #{idx}: {reel_url} ---")
        output_filename = f"video_{idx}.mp4"

        caption = ""
        try:
            desc_cmd = [
                "yt-dlp",
                "--cookies", cookie_file,
                "--no-check-certificates",
                "--dump-json",
                reel_url
            ]
            info_res = subprocess.run(desc_cmd, capture_output=True, text=True)
            if info_res.stdout:
                info_json = json.loads(info_res.stdout)
                caption = info_json.get("description") or info_json.get("title") or ""
        except Exception as e:
            print(f"Erro ao capturar legenda: {e}")

        cmd = [
            "yt-dlp",
            "--cookies", cookie_file,
            "--no-check-certificates",
            "--merge-output-format", "mp4",
            "-f", "bestvideo+bestaudio/best",
            "-o", output_filename,
            "--force-overwrites",
            reel_url
        ]
        subprocess.run(cmd, capture_output=True, text=True)

        posts_data.append({
            "id": idx,
            "url": reel_url,
            "video_file": output_filename,
            "caption": caption.strip() if caption else "L2 Centro de Treinamento - Treino de verdade e evolução constante.",
            "updated_at": time.strftime("%d/%m/%Y às %H:%M")
        })

    cleanup_old_videos(allowed_videos)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(posts_data, f, ensure_ascii=False, indent=2)

    if os.path.exists(cookie_file):
        os.remove(cookie_file)

    print("\n✅ Concluído! Todos os vídeos e dados do L2 foram gerados.")

if __name__ == "__main__":
    main()
