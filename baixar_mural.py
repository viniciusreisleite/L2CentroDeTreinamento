# -*- coding: utf-8 -*-
import json
import os
import subprocess
import glob
import time
import random
from http.cookiejar import MozillaCookieJar
from playwright.sync_api import sync_playwright

PERFIL_ALVO = "l2_centrodetreinamento"
LIMITE_POSTS = 15

PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_JSON = os.path.join(PASTA_ATUAL, "data.json")
ARQUIVO_COOKIES = os.path.join(PASTA_ATUAL, "cookies.txt")

def rodar_comando_git(comando):
    resultado = subprocess.run(comando, cwd=PASTA_ATUAL, capture_output=True, text=True)
    if resultado.stdout:
        print(resultado.stdout.strip())
    if resultado.stderr and resultado.returncode != 0:
        print(f"Git: {resultado.stderr.strip()}")
    return resultado.returncode == 0

def carregar_cookies_playwright():
    if not os.path.exists(ARQUIVO_COOKIES):
        return []
    cj = MozillaCookieJar(ARQUIVO_COOKIES)
    cj.load(ignore_discard=True, ignore_expires=True)
    playwright_cookies = []
    for c in cj:
        domain = c.domain
        if not domain.startswith("."):
            domain = "." + domain
        playwright_cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": domain,
            "path": c.path,
            "secure": c.secure,
            "httpOnly": False
        })
    return playwright_cookies

def obter_links_perfil_playwright(usuario, limite=15):
    print(f"Carregando posts mais recentes de @{usuario}...")
    posts_coletados = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )

        cookies = carregar_cookies_playwright()
        if cookies:
            context.add_cookies(cookies)

        page = context.new_page()
        page.goto(f"https://www.instagram.com/{usuario}/", wait_until="networkidle", timeout=60000)
        time.sleep(3)

        links_vistos = set()
        tentativas_scroll = 0

        while len(posts_coletados) < limite and tentativas_scroll < 15:
            elementos = page.locator("a[href*='/p/'], a[href*='/reel/']").all()

            for item in elementos:
                try:
                    href = item.get_attribute("href")
                    if not href or href in links_vistos:
                        continue

                    clean_path = href.split("?")[0].rstrip("/")
                    partes = clean_path.split("/")
                    if len(partes) < 3 or partes[-2] not in ["p", "reel"]:
                        continue

                    links_vistos.add(href)
                    full_url = f"https://www.instagram.com{clean_path}/"

                    # Checa ícone de pin/fixado
                    parent = item.locator("xpath=ancestor::div[1]")
                    if parent.locator("svg[aria-label*='Fixado'], svg[aria-label*='Pinned'], svg[aria-label*='fixado']").count() > 0:
                        print(f"-> Post fixado ignorado: {full_url}")
                        continue

                    posts_coletados.append(full_url)
                    if len(posts_coletados) >= limite:
                        break
                except Exception:
                    continue

            page.mouse.wheel(0, 1800)
            time.sleep(2)
            tentativas_scroll += 1

        browser.close()

    return posts_coletados

def baixar_midia_otimizada(url, nome_base):
    template_saida = os.path.join(PASTA_ATUAL, f"{nome_base}.%(ext)s")

    cmd_video = [
        "python", "-m", "yt_dlp",
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "--merge-output-format", "mp4",
        "--postprocessor-args", "VideoConvertor:-vcodec libx264 -crf 23 -preset fast -c:a aac -b:a 128k",
        "-o", template_saida,
        url
    ]
    if os.path.exists(ARQUIVO_COOKIES):
        cmd_video.extend(["--cookies", ARQUIVO_COOKIES])

    subprocess.run(cmd_video, capture_output=True, text=True)

    arquivos = glob.glob(os.path.join(PASTA_ATUAL, f"{nome_base}.mp4"))
    if arquivos:
        return arquivos[0], "video"

    cmd_foto = [
        "python", "-m", "yt_dlp",
        "--skip-download",
        "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "-o", template_saida,
        url
    ]
    if os.path.exists(ARQUIVO_COOKIES):
        cmd_foto.extend(["--cookies", ARQUIVO_COOKIES])

    subprocess.run(cmd_foto, capture_output=True, text=True)

    arquivos = glob.glob(os.path.join(PASTA_ATUAL, f"{nome_base}.*"))
    if arquivos:
        return arquivos[0], "image"

    return None, None

def obter_legenda(url):
    cmd = ["python", "-m", "yt_dlp", "--dump-json", "--skip-download", url]
    if os.path.exists(ARQUIVO_COOKIES):
        cmd.extend(["--cookies", ARQUIVO_COOKIES])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.stdout:
            meta = json.loads(proc.stdout)
            return meta.get("description") or meta.get("title") or ""
    except Exception:
        pass
    return ""

def processar_mural():
    urls = obter_links_perfil_playwright(PERFIL_ALVO, LIMITE_POSTS)

    if not urls:
        print("Nenhum post retornado.")
        return

    print(f"\nEncontrados {len(urls)} posts! Baixando mídias (máx 720p)...")

    # Limpar mídias antigas
    for antigo in glob.glob(os.path.join(PASTA_ATUAL, "media_*.*")):
        try:
            os.remove(antigo)
        except OSError:
            pass

    itens_json = []
    contador = 1

    for pos, url in enumerate(urls, start=1):
        print(f"\n[{pos}/{len(urls)}] Baixando: {url}")
        nome_base = f"media_{contador}"

        arquivo_salvo, tipo = baixar_midia_otimizada(url, nome_base)

        if arquivo_salvo:
            nome_arquivo = os.path.basename(arquivo_salvo)
            tamanho_mb = os.path.getsize(arquivo_salvo) / (1024 * 1024)
            legenda = obter_legenda(url)
            print(f"Salvo ({tipo}): {nome_arquivo} - {tamanho_mb:.2f} MB")

            # Compatibilidade direta com index.html sem mexer no HTML
            itens_json.append({
                "id": contador,
                "file": nome_arquivo,
                "media_file": nome_arquivo,
                "video_file": nome_arquivo,
                "type": tipo,
                "caption": legenda,
                "source_url": url
            })
            contador += 1
        else:
            print(f"Falha ao baixar {url}")

        time.sleep(random.uniform(1.0, 2.0))

    with open(ARQUIVO_JSON, "w", encoding="utf-8") as jf:
        json.dump(itens_json, jf, indent=2, ensure_ascii=False)

    print(f"\nFinalizado! {len(itens_json)} mídias salvas.")

    print("\n--- Sincronizando com o GitHub ---")
    rodar_comando_git(["git", "add", "-A"])
    rodar_comando_git(["git", "commit", "-m", "Mural sincronizado: 720p e chaves compativeis"])
    sucesso_push = rodar_comando_git(["git", "push", "origin", "main"])

    if sucesso_push:
        print("Sincronização concluída com sucesso no GitHub!")

if __name__ == "__main__":
    processar_mural()
