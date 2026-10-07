@echo off
REM  Кодировка консоли — UTF-8. Файл сохранён в UTF-8 БЕЗ BOM, иначе
REM  первая строка превратится в "п»ї@echo off" и cmd не поймёт её.
REM  cmd.exe без chcp читает байты в кодовой странице консоли (на русской
REM  Windows — 866), и весь русский текст в этом файле превращается в кашу.
REM  Меняем страницу сразу, до первого echo.
chcp 65001 >nul

REM ============================================================
REM  zagent - единственная точка входа
REM
REM  Двойной клик: поднимает окружение, запускает агента с веб-интерфейсом
REM  и открывает панель в браузере.
REM
REM  Команды из командной строки (в той же папке):
REM
REM    zagent.bat                 панель агента (по умолчанию)
REM    zagent.bat check           проверить окружение
REM    zagent.bat ask  "вопрос"   спросить модель через failover
REM    zagent.bat agent "задача"  задача агенту из консоли
REM    zagent.bat modes           список моделей с приоритетами
REM    zagent.bat ping            пинговать всё, записать отчёт
REM    zagent.bat sanity          проверить адекватность моделей
REM    zagent.bat consult "вопрос"  спросить 3 модели
REM    zagent.bat connect opencode  инструкция по подключению
REM    zagent.bat export opencode   готовый конфиг (в stdout)
REM    zagent.bat ws  list|add|rm|use   воркспейсы
REM    zagent.bat test            прогнать тесты
REM
REM  Чтобы закрепить за файлом: правый клик -> Открыть с помощью -> zagent.bat
REM  Чтобы запускать без окна консоли: создайте ярлык с командой
REM      cmd /c start "" "%~f0" ^
REM ============================================================

REM  Без enabledelayedexpansion: опция портит всё, что содержит «!», уже на
REM  этапе set. Путь «C:\work\!wip\zagent» или аргумент «почини!баг!» теряли
REM  символы молча.
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
set "CMD=%~1"
if not defined CMD set "CMD=ui"

REM  Хвост аргументов собираем ПОСЛЕ shift: имя команды уже не %1, поэтому
REM  в REST попадут только аргументы. Без этого `ask "вопрос"` уходил в
REM  python как `ask ask "вопрос"`, `ws list` — как `ws ws list`, а `web`
REM  превращался в `serve.py web` и падал на argparse.
shift

set "REST="
:collectargs
if "%~1"=="" goto :argsready
set "REST=%REST% %1"
shift
goto :collectargs
:argsready

REM ============================================================
REM  Подготовка окружения (один раз, дальше пропускаем)
REM ============================================================
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Первая настройка: создаю .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Не получилось создать виртуальное окружение.
        echo Установите Python 3.11+ и запустите файл снова.
        goto :fail
    )
    call :install
    if errorlevel 1 (
        echo.
        echo Не получилось поставить зависимости — нужен интернет.
        echo Проверьте подключение и запустите файл снова.
        goto :fail
    )
    echo   Готово.
    echo.
)

REM  Без pyyaml стенд проверки агента не читает задания: он хранит их в YAML.
REM  Проверяем именно этот пакет, потому что базовая проверка выше
REM  смотрит только на httpx и PIL и с pyyaml ничего не скажет.
"%PY%" -c "import httpx, PIL, yaml" 2>nul || (
    echo   Ставлю зависимости ...
    call :install
    if errorlevel 1 (
        echo.
        echo Зависимости поставить не удалось — нужен интернет.
        goto :fail
    )
)

REM ============================================================
REM  Команды
REM ============================================================

if /i "%CMD%"=="ui"        goto :ui
if /i "%CMD%"=="web"       goto :ui
if /i "%CMD%"=="check"     goto :check
if /i "%CMD%"=="ask"       goto :ask
if /i "%CMD%"=="agent"     goto :agent
if /i "%CMD%"=="modes"     goto :modes
if /i "%CMD%"=="ping"      goto :ping
if /i "%CMD%"=="sanity"    goto :sanity
if /i "%CMD%"=="consult"   goto :consult
if /i "%CMD%"=="connect"   goto :connect
if /i "%CMD%"=="export"    goto :export
if /i "%CMD%"=="geo"       goto :geo
if /i "%CMD%"=="ws"        goto :ws
if /i "%CMD%"=="bench"     goto :bench
if /i "%CMD%"=="test"      goto :test
if /i "%CMD%"=="help"      goto :help
if /i "%CMD%"=="/?"        goto :help

echo Неизвестная команда: %CMD%
goto :help

REM ---------------------------------------------------------------- UI
:ui
echo.
echo   zagent
echo   ----------------------------------------------
echo.
if not exist "config\secrets.local.json" (
    echo   Ключи не настроены. Работать будет только часть
    echo   шлюзов ^(llm7.io, OpenCode Zen, локальный Ollama^).
    echo.
    echo   Скопируйте шаблон и вставьте свои ключи:
    echo       copy config\secrets.local.json.example config\secrets.local.json
    echo.
    timeout /t 6 /nobreak >nul
)

REM Браузер ищется в типовых местах Chrome и передаётся serve.py явно:
REM открывать «по умолчанию» нельзя — в Windows по умолчанию нередко
REM стоит Edge, а человек работает именно в Chrome. Если Chrome не
REM найден, serve.py откроет адрес браузером системы.
set "CHROME="
for %%P in (
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Chromium\Application\chrome.exe"
) do if exist "%%~P" if not defined CHROME set "CHROME=%%~P"

echo   Интерфейс:      http://127.0.0.1:8783
echo   Панель шлюза:   http://127.0.0.1:8784  ^(дебагер и модели^)
if defined CHROME (
    echo   Браузер:       Chrome ^(оба адреса откроются сами^)
) else (
    echo   Браузер:       по умолчанию ^(Chrome не найден^)
)
echo   Остановить: закройте это окно или Ctrl+C
echo.
if defined CHROME (
    "%PY%" tools\serve.py --browser "%CHROME%" %REST%
) else (
    "%PY%" tools\serve.py %REST%
)
exit /b %errorlevel%

REM ---------------------------------------------------------------- check
:check
"%PY%" tools\check_env.py
set "code=%errorlevel%"
echo.
if "%code%"=="0" (echo   Всё работает. Запуск: zagent.bat) else (echo   Есть проблемы, смотрите выше.)
echo.
if not defined ZAGENT_NO_PAUSE pause
exit /b %code%

REM ---------------------------------------------------------------- ask
:ask
if "%REST%"=="" (
    echo   Использование: zagent.bat ask "вопрос"
    pause
    exit /b 1
)
"%PY%" tools\agent.py ask %REST%
exit /b %errorlevel%

REM ---------------------------------------------------------------- agent
:agent
if "%REST%"=="" (
    echo   Использование: zagent.bat agent [--access 1-3] [--autonomy yolo^|normal^|strict^|plan] "задача"
    pause
    exit /b 1
)
"%PY%" tools\agent.py %REST%
exit /b %errorlevel%

REM ---------------------------------------------------------------- modes
:modes
"%PY%" tools\agent.py modes
exit /b %errorlevel%

REM ---------------------------------------------------------------- ping
:ping
"%PY%" tools\cli.py ping --write
exit /b %errorlevel%

REM ---------------------------------------------------------------- sanity
:sanity
"%PY%" tools\agent.py sanity %REST%
exit /b %errorlevel%

REM ---------------------------------------------------------------- consult
:consult
if "%REST%"=="" (
    echo   Использование: zagent.bat consult "вопрос" [-n 3]
    pause
    exit /b 1
)
"%PY%" tools\agent.py consult %REST%
exit /b %errorlevel%

REM ---------------------------------------------------------------- connect
:connect
if "%REST%"=="" (
    echo.
    echo   Инструкции по подключению моделей в другой софт.
    echo.
    echo   Использование: zagent.bat connect [opencode^|deepseek^|codex^|zed^|cline]
    echo.
    echo   Без аргумента печатает сводку по всем инструментам.
    echo.
    "%PY%" tools\connect_guide.py
    pause
    exit /b 0
)
"%PY%" tools\connect_guide.py %REST%
exit /b %errorlevel%

REM ---------------------------------------------------------------- export
:export
if "%REST%"=="" (
    echo   Использование: zagent.bat export opencode^|codex^|zed^|cline^|plain
    pause
    exit /b 1
)
"%PY%" tools\cli.py export %REST%
exit /b %errorlevel%

REM ---------------------------------------------------------------- geo
:geo
if "%REST%"=="" (
    echo.
    echo   Доступность моделей из России измеряется в двух режимах.
    echo.
    echo     zagent.bat geo --direct    ВЫКЛЮЧИТЕ vpn, потом эта команда
    echo     zagent.bat geo --vpn       ВКЛЮЧИТЕ vpn, потом эта команда
    echo.
    echo   Один замер с включённым vpn ничего не доказывает: через vpn
    echo   отвечает почти всё. Вердикт "работает без vpn" ставится только
    echo   по замеру --direct, и он не затирается последующим замером.
    echo.
    pause
    exit /b 1
)
"%PY%" tools\geo.py %REST%
set "code=%errorlevel%"
if not defined ZAGENT_NO_PAUSE pause
exit /b %code%

REM ---------------------------------------------------------------- ws
:ws
"%PY%" tools\workspace.py %REST%
set "code=%errorlevel%"
if not defined ZAGENT_NO_PAUSE pause
exit /b %code%

REM ---------------------------------------------------------------- bench
REM  Стенд проверки агента: задания в tasks\, эталоны в ref\.
REM  Без аргументов показывает список заданий - как приём, который ничего не
REM  тратит. Аргументы после bench уходят скрипту как есть.
:bench
if "%REST%"=="" (
    "%PY%" tools\bench.py list
) else (
    "%PY%" tools\bench.py %REST%
)
set "code=%errorlevel%"
if not defined ZAGENT_NO_PAUSE pause
exit /b %code%

REM ---------------------------------------------------------------- test
:test
"%PY%" -m pytest -q
exit /b %errorlevel%

REM ---------------------------------------------------------------- help
:help
echo.
echo   zagent - команды
echo   ==============================================
echo.
echo   Основное
echo     ^(двойной клик по файлу^)     панель агента в браузере
echo     zagent.bat                   то же самое явно
echo     zagent.bat check             проверить окружение
echo.
echo   Работа с моделями
echo     zagent.bat modes             список моделей с приоритетами
echo     zagent.bat ping              пинговать всё и записать отчёт
echo     zagent.bat sanity            проверить адекватность моделей
echo     zagent.bat ask "вопрос"     спросить модель через failover
echo     zagent.bat consult "вопрос"  спросить 3 модели и сравнить
echo.
echo   Доступность из России
echo     zagent.bat geo --direct      замер БЕЗ vpn ^(выключите vpn сначала^)
echo     zagent.bat geo --vpn         замер С vpn ^(включите vpn сначала^)
echo.
echo   Подключение к другому софту
echo     zagent.bat connect           инструкции для всех инструментов
echo     zagent.bat connect opencode  инструкция для одного инструмента
echo     zagent.bat export opencode   готовый конфиг в stdout
echo.
echo   Агент
echo     zagent.bat agent "задача"    задача из командной строки
echo     zagent.bat agent --access 3 --autonomy normal "задача"
echo     zagent.bat ws list           список воркспейсов
echo     zagent.bat ws add C:\work    добавить папку для агента
echo     zagent.bat ws use work       переключиться на воркспейс
echo.
echo   Разработка
echo     zagent.bat test              прогнать тесты
echo     zagent.bat bench             список заданий стенда
echo     zagent.bat bench run all --dry  проверить стенд без моделей
echo.
pause
exit /b 0

REM ============================================================
:install
    REM  Код возврата pip передаётся вызывающему: иначе bat печатал
    REM  «Готово» после неудачной установки, а потом запускал serve.py
    REM  и закрывал окно с ModuleNotFoundError.
    "%PY%" -m pip install --quiet --upgrade pip
    if errorlevel 1 exit /b 1
    "%PY%" -m pip install --quiet -r requirements.txt
    if errorlevel 1 exit /b 1
    exit /b 0

:fail
echo.
pause
exit /b 1