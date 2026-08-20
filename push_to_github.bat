@echo off
REM ============================================
REM AutoPost — enviar ao GitHub em um clique
REM ============================================
echo.
echo  [1/4] Verificando Git instalado...
where git >nul 2>nul
if %errorlevel% neq 0 (
    echo  ERRO: Git nao encontrado.
    echo  Baixe em: https://git-scm.com/download/win
    echo  Durante a instalacao, deixe as opcoes padrao marcadas.
    pause
    exit /b 1
)

echo  [2/4] Qual o nome do seu repositorio no GitHub?
echo  (crie-o primeiro em https://github.com/new com o mesmo nome)
set /p REPO=Nome do repositorio (ex.: AutoPost):

echo  [3/4] Qual seu usuario do GitHub? (ex.: eriton123)
set /p USER=Usuario do GitHub:

echo  [4/4] Conectando e enviando...
git remote set-url origin https://github.com/%USER%/%REPO%.git
git branch -M main
git add .
git commit -m "AutoPost V7.7 - agendador automatico YouTube/Instagram/TikTok" -q
git push -u origin main

if %errorlevel% equ 0 (
    echo.
    echo  SUCESSO! Repositorio em: https://github.com/%USER%/%REPO%
) else (
    echo.
    echo  Falha no envio. Verifique nome do repositorio e usuario.
)
pause
