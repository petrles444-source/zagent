@echo off
REM  Пересобрать zradio.exe из zradio.cs.
REM
REM  Лаунчер — это C# без единой зависимости: он ищет .venv рядом с собой
REM  и запускает tools\zradio.py. Компилятор берётся из .NET Framework,
REM  который есть в любой Windows, — в отличие от dotnet SDK, которого
REM  может не быть.
REM
REM  Пути строим от %~dp0, а не через cd: bat лежит в tools\, а собранный
REM  exe обязан оказаться в корне — C# ищет .venv и tools\zradio.py
REM  относительно СВОЕГО расположения.
REM
REM  Кодировка консоли — UTF-8, файл сохранён в UTF-8 БЕЗ BOM: иначе
REM  первая строка превратится в "п»ї@echo off" и cmd её не поймёт.
REM  Файл обязан быть в CRLF: cmd.exe рвёт блоки в скобках на одних LF.
chcp 65001 >nul
setlocal

set CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" goto nocsc

"%CSC%" /nologo /out:"%~dp0..\zradio.exe" "%~dp0zradio.cs"
if errorlevel 1 goto failed

echo Собрано: zradio.exe
exit /b 0

:nocsc
echo Не найден компилятор .NET Framework ^(csc.exe^).
echo Обычно он лежит в C:\Windows\Microsoft.NET\Framework64\v4.0.30319\.
exit /b 1

:failed
echo Сборка не удалась.
exit /b 1
