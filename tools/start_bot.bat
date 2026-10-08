@echo off
REM  Поднять помощника сайта целиком: агент, прокси, туннель.
REM
REM  Зачем скрипт, если всё можно запустить руками: адрес быстрого
REM  туннеля меняется при каждом перезапуске. Поменялся он — значит
REM  страница на сайте обращается в никуда, и бот молчит. Скрипт
REM  читает новый адрес, вписывает его в site\assets\config.json и
REM  заливает на хостинг, поэтому после перезапуска ничего править
REM  руками не нужно.
REM
REM  Кодировка консоли — UTF-8, файл в UTF-8 БЕЗ BOM и обязательно в
REM  CRLF: cmd.exe рвёт блоки в скобках на одних LF.
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0\.."

set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  echo Нет виртуального окружения: %PY%
  echo Создай его и поставь зависимости, потом запусти скрипт снова.
  exit /b 1
)

REM ---------- 1. агент ----------
REM  Порт занят — значит агент уже поднят, второй не нужен: два
REM  экземпляра делят очередь задач и путают журнал.
curl.exe -s -o nul -w "" --connect-timeout 5 --max-time 8 http://127.0.0.1:8783/api/state
if errorlevel 1 (
  echo [1/4] запускаю агента...
  start "" /b "%PY%" tools\serve.py
) else (
  echo [1/4] агент уже работает
)

REM ---------- 2. прокси ----------
curl.exe -s -o nul -w "" --connect-timeout 5 --max-time 8 http://127.0.0.1:8790/health
if errorlevel 1 (
  echo [2/4] запускаю прокси...
  start "" /b "%PY%" tools\bot_proxy.py --port 8790
) else (
  echo [2/4] прокси уже работает
)

REM ---------- 3. туннель ----------
if not exist tmp\bin\cloudflared.exe (
  echo Нет tmp\bin\cloudflared.exe — скачай его:
  echo   https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
  echo и положи в tmp\bin\
  exit /b 1
)
echo [3/4] поднимаю туннель...
REM  stdin уводится в NUL: cloudflared отказывается работать с
REM  перенаправленным вводом и сразу выходит («Input redirection is
REM  not supported»). Пустой ввод для него — нормальный режим.
start "" /b tmp\bin\cloudflared.exe tunnel --url http://127.0.0.1:8790 --no-autoupdate < NUL > tmp\tunnel.log 2>&1

REM  Адрес появляется через несколько секунд. Ждём и вычитываем.
set ADDR=
for /l %%i in (1,1,20) do (
  if not defined ADDR (
    for /f "tokens=2" %%a in ('findstr /r /c:"https://.*trycloudflare.com" tmp\tunnel.log 2^>nul') do set ADDR=%%a
    if not defined ADDR timeout /t 2 /nobreak >nul
  )
)
if not defined ADDR (
  echo Не дождался адреса туннеля. Смотри tmp\tunnel.log
  exit /b 1
)
echo       адрес: %ADDR%

REM ---------- 4. конфиг и заливка ----------
echo [4/4] вписываю адрес и заливаю...
set PYTHONIOENCODING=utf-8
"%PY%" -c "import json,pathlib;p=pathlib.Path('site/assets/config.json');d=json.loads(p.read_text(encoding='utf-8'));d['bot_endpoint']='%ADDR%';p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')"
if errorlevel 1 (
  echo Не записался конфиг.
  exit /b 1
)
"%PY%" tools\build_site.py
if errorlevel 1 exit /b 1

REM Заливаем только конфиг: остальное на сервере уже лежит и весит
REM двадцать девять мегабайт.
set ZAGENT_FTP_HOST=s726.ucoz.net
set ZAGENT_FTP_USER=8zagent
if "%ZAGENT_FTP_PASS%"=="" (
  echo Нет ZAGENT_FTP_PASS — конфиг на сервер не попал.
  echo Задай пароль и повтори:  set ZAGENT_FTP_PASS=...
  echo Адрес прокси: %ADDR%
  exit /b 1
)
"%PY%" -c "import ftplib,os,pathlib;p=pathlib.Path('site-dist/config.json');f=ftplib.FTP();f.connect(os.environ['ZAGENT_FTP_HOST'],timeout=60);f.login(os.environ['ZAGENT_FTP_USER'],os.environ['ZAGENT_FTP_PASS']);f.set_pasv(True);f.voidcmd('TYPE I');f.storbinary('STOR config.json',p.open('rb'));f.quit();print('config.json залит')"

echo.
echo Готово. Помощник доступен на %ADDR%
echo Бот работает, пока открыты: агент, прокси и туннель.
exit /b 0
