@echo off
REM Собрать установщик AllVPN из исходника.
REM
REM Компилятор берётся из .NET Framework — он есть в любой Windows.
REM В отличие от dotnet SDK, которого может не быть.
REM
REM Кодировка — UTF-8 БЕЗ BOM, строки в CRLF: иначе первая строка
REM превратится в мусор, а cmd.exe рвёт блоки в скобках на одних LF.
REM
REM Здесь НЕТ `chcp 65001`: с ним cmd начинает разбирать кириллицу в
REM строках как команды — проверено, сборка падает с «'в' is not
REM recognized». Кодировку выставляет вызывающий скрипт, где нет
REM кириллицы в исполняемых строках.
setlocal

set CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" goto nocsc

"%CSC%" /nologo /out:"%~dp0..\dist\allvpn\allvpn-setup.exe" "%~dp0allvpn_setup.cs"
if errorlevel 1 goto failed

echo Собрано: dist\allvpn\allvpn-setup.exe
exit /b 0

:nocsc
echo Не найден компилятор .NET Framework ^(csc.exe^).
echo Обычно он лежит в C:\Windows\Microsoft.NET\Framework64\v4.0.30319\
exit /b 1

:failed
echo Сборка не удалась.
exit /b 1
