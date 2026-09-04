@echo off
cd /d "%~dp0"
echo ======================================================
echo Atualizando mural: L2CentroDeTreinamento (@l2_centrodetreinamento)
echo ======================================================
python baixar_mural.py

echo Enviando atualizacoes para o GitHub Pages...
git add data.json media_*.mp4
git diff-index --quiet HEAD || git commit -m "Atualizacao automatica mural"
git push origin main

echo Concluido! Em ~40s o painel estara atualizado.
timeout /t 5