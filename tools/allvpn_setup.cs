// allvpn-setup.exe — установщик AllVPN.
//
// Задача: разложить всё нужное в одну папку и объяснить, что делать
// дальше. Само приложение на Python, поэтому «установка» — это
// проверка окружения, установка недостающих пакетов и запуск.
//
// Почему так сложно, когда можно сказать «pip install»
// -------------------------------------------------------
// Пользователь AllVPN — человек, который не хочет разбираться в
// Python. Он пришёл за программой, а не за командой в терминале.
// Установщик делает ровно то же, что иначе пришлось бы сделать
// руками: найти интерпретатор, поставить недостающее, проверить, что
// всё импортируется, и только потом запустить. Каждый шаг
// проговаривается словами, потому что ошибка на любом из них без
// объяснения выглядит как «программа сломалась».
//
// Про Python
// ----------
// Требование — Python 3.11 или новее. Раньше нельзя: приложение
// использует match/case и современные подсказки типов. В коде стоит
// проверка версии с понятным сообщением, а не «SyntaxError» на
// середине запуска.
//
// Про зависимости
// ---------------
// pystray нужен для значка в трее, Pillow рисует его картинку, numpy
// считает скорость на серверах. Ставим только то, чего не хватает:
// повторная установка того, что уже есть, тратит минуты и может
// сломать рабочее окружение.
//
// Сборка (компилятор .NET Framework есть в любой Windows):
//   tools\build_allvpn_setup.bat
//
// Кодировка: UTF-8 БЕЗ BOM, CRLF. Иначе первая строка превратится в
// мусор и cmd её не поймёт.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;

static class AllVpnSetup
{
    // Куда ставим: папка установки пользователя, а не Program Files.
    // В Program Files нельзя писать без прав администратора, а
    // приложение пишет туда конфиг и логи.
    const string AppFolder = "AllVPN";

    static string Root
    {
        get
        {
            // Папка установщика — она и есть корень установки.
            return Path.GetDirectoryName(
                Path.GetFullPath(
                    System.Reflection.Assembly.GetExecutingAssembly().Location));
        }
    }

    static int Main(string[] args)
    {
        try
        {
            Console.OutputEncoding = Encoding.UTF8;
        }
        catch { /* старая консоль может не уметь — не критично */ }

        Console.WriteLine("============================================");
        Console.WriteLine("  AllVPN — установка");
        Console.WriteLine("============================================");
        Console.WriteLine();

        // ---- 1. Где ставим ----
        string target = args.Length > 0 ? args[0]
                                        : Path.Combine(
                                            Environment.GetFolderPath(
                                                Environment.SpecialFolder.LocalApplicationData),
                                            AppFolder);

        Console.WriteLine("Папка установки: " + target);
        try
        {
            Directory.CreateDirectory(target);
        }
        catch (Exception e)
        {
            Fail("не удалось создать папку установки: " + e.Message);
            return 1;
        }

        // ---- 2. Копируем программу ----
        Console.WriteLine();
        Console.WriteLine("Копирование программы...");

        int copied = 0;
        int skipped = 0;

        // Копируется ПАКЕТ, а не содержимое папки установщика.
        // `python -m allvpn.app` требует, чтобы рядом лежала папка
        // `allvpn` с `__init__.py`. Если копировать файлы «в плоскость»,
        // получится набор .py без пакета, и проверка честно скажет
        // «No module named allvpn» — хотя файлы скопированы все.
        string packageSource = FindPackageDir();
        if (packageSource == null)
        {
            Console.WriteLine();
            Console.WriteLine("[ОШИБКА] Не найдена папка программы allvpn.");
            Console.WriteLine("  Установщик должен лежать рядом с папкой allvpn,");
            Console.WriteLine("  внутри которой есть __init__.py и app.py.");
            Console.WriteLine("  Сейчас установщик лежит здесь: " + Root);
            return 1;
        }
        Console.WriteLine("  исходники: " + packageSource);

        // Папка назначения не должна копироваться сама в себя:
        // установщик часто лежит рядом с программой, и без проверки
        // рекурсия уходит в саму себя, а путь растёт до отказа
        // Windows «путь слишком длинный» без внятной причины.
        string targetFull = Path.GetFullPath(target)
            .TrimEnd(Path.DirectorySeparatorChar);

        try
        {
            CopyTree(packageSource, Path.Combine(target, "allvpn"),
                     ref copied, targetFull);

            // Расширение для браузера едет вместе с программой: без него
            // установка неполная, а отдельно его искать некому.
            string ext = Path.Combine(
                Path.GetDirectoryName(packageSource), "extension");
            if (Directory.Exists(ext) && !IsInsideTarget(ext, targetFull))
            {
                CopyTree(ext, Path.Combine(target, "extension"),
                         ref copied, targetFull);
                Console.WriteLine("  расширение для браузера: extension\\");
            }

            // Ядро sing-box — большой бинарник, без него не работает
            // сам VPN. Копируем, если рядом есть.
            string bin = Path.Combine(
                Path.GetDirectoryName(packageSource), "bin");
            if (Directory.Exists(bin) && !IsInsideTarget(bin, targetFull))
            {
                CopyTree(bin, Path.Combine(target, "allvpn", "bin"),
                         ref copied, targetFull);
            }

            // Значки для трея.
            string icons = Path.Combine(
                Path.GetDirectoryName(packageSource), "icons");
            if (Directory.Exists(icons) && !IsInsideTarget(icons, targetFull))
            {
                CopyTree(icons, Path.Combine(target, "allvpn", "icons"),
                         ref copied, targetFull);
            }
        }
        catch (Exception e)
        {
            Fail("ошибка при копировании: " + e.Message);
            return 1;
        }
        Console.WriteLine("  скопировано файлов: " + copied +
                          (skipped > 0 ? ", пропущено папок: " + skipped : ""));

        // ---- 3. Ищем Python ----
        Console.WriteLine();
        Console.WriteLine("Поиск Python...");
        string python = FindPython();
        if (python == null)
        {
            Console.WriteLine();
            Console.WriteLine("[НУЖНО] Python не найден.");
            Console.WriteLine();
            Console.WriteLine("  Установи Python 3.11 или новее:");
            Console.WriteLine("    https://www.python.org/downloads/");
            Console.WriteLine();
            Console.WriteLine("  При установке ОБЯЗАТЕЛЬНО поставь галочку");
            Console.WriteLine("  «Add Python to PATH». Потом запусти этот файл снова.");
            Console.WriteLine();
            Console.WriteLine("Папка, куда всё подготовлено: " + target);
            Console.WriteLine("Запусти install.cmd из неё, когда поставишь Python.");
            return 2;
        }
        Console.WriteLine("  найден: " + python);

        // ---- 4. Версия Python ----
        // Приложение использует современный синтаксис, и на старой
        // версии пользователь увидит SyntaxError без объяснения.
        string version;
        if (!PythonVersionOk(python, out version))
        {
            Console.WriteLine();
            Console.WriteLine("[НУЖНО] Python " + version +
                              " слишком старый. Нужен 3.11 или новее.");
            Console.WriteLine("Поставь новую версию и запусти установщик снова.");
            return 2;
        }
        Console.WriteLine("  версия: " + version + " — подходит");

        // ---- 5. Зависимости ----
        Console.WriteLine();
        Console.WriteLine("Проверка зависимостей...");

        // Имя для установки и имя модуля для импорта — разные вещи:
        // Pillow ставится как `Pillow`, а импортируется как `PIL`.
        // Отсюда раньше и выходила ошибка «Could not find a version
        // that satisfies the requirement PIL» — такого пакета нет.
        var needed = new[]
        {
            new KeyValuePair<string, string>("pystray",  "pystray"),
            new KeyValuePair<string, string>("Pillow",   "PIL"),
            new KeyValuePair<string, string>("numpy",    "numpy"),
        };

        string check = BuildCheckScript(needed);
        string found;
        if (!RunPython(python, check, 60, out found))
        {
            Console.WriteLine("  не удалось проверить, ставлю всё подряд");
            found = "";
        }
        found = found.Trim();

        var missing = new System.Collections.Generic.List<string>();
        foreach (var pair in needed)
        {
            if (!found.Contains(pair.Key))
            {
                missing.Add(pair.Key);
                Console.WriteLine("  нет: " + pair.Key);
            }
            else
            {
                Console.WriteLine("  есть: " + pair.Key);
            }
        }

        if (missing.Count > 0)
        {
            Console.WriteLine();
            Console.WriteLine("Установка недостающих пакетов. Это займёт минуту...");
            string pipArgs = "-m pip install --disable-pip-version-check " +
                             "--no-input " + string.Join(" ", missing.ToArray());
            string pipOut;
            RunPython(python, pipArgs, 900, out pipOut);
            if (pipOut.Length > 0)
            {
                // Вывод pip показываем целиком: если что-то не
                // поставилось, причина будет именно здесь, а не
                // в абстрактном «программа не запустилась».
                Console.WriteLine(pipOut);
            }

            // Проверяем ещё раз. Если пакет не поставился, сообщаем
            // честно и продолжаем: может, приложение работает и без него.
            string again;
            if (!RunPython(python, check, 60, out again)) again = "";
            again = again.Trim();
            foreach (string pkg in missing)
            {
                if (!again.Contains(pkg))
                {
                    Console.WriteLine("  [ВНИМАНИЕ] не удалось поставить: " + pkg);
                }
            }
        }

        // ---- 6. Проверка, что всё импортируется ----
        Console.WriteLine();
        Console.WriteLine("Проверка запуска...");
        string probe = BuildProbeScript();
        string probeOut;
        // Проверять надо из папки УСТАНОВЛЕННОЙ программы. Если оставить
        // рабочей папку установщика, поиск `allvpn` идёт рядом с exe,
        // где его нет, и проверка рапортует «No module named allvpn»,
        // хотя программа только что скопирована и в порядке.
        bool probeOk = RunPythonIn(python, probe, 120, target, out probeOut);
        if (probeOk)
        {
            Console.WriteLine("  " + probeOut.Trim());
            Console.WriteLine("  всё в порядке");
        }
        else
        {
            Console.WriteLine();
            Console.WriteLine("[ОШИБКА] Программа не проходит проверку:");
            Console.WriteLine(probeOut);
            Console.WriteLine("Папка установки: " + target);
            Console.WriteLine("Посмотреть подробности: " +
                              Path.Combine(target, "install.log"));
            WriteInstallLog(Path.Combine(target, "install.log"), probeOut);
            return 1;
        }

        // ---- 7. Файлы запуска ----
        // И run.bat, и INSTALL.txt создаются здесь же, а не
        // «где-то потом»: раньше установщик печатал «Готово: run.bat»,
        // но файла не было — и человек, доверившийся надписи, получал
        // пустую папку и сообщение об ошибке вместо работающей
        // программы. Надпись на экране и содержимое папки должны
        // совпадать.
        string runPath = Path.Combine(target, "run.bat");
        string notePath = Path.Combine(target, "INSTALL.txt");
        try
        {
            File.WriteAllText(runPath, BuildCmd(python), new UTF8Encoding(true));
            File.WriteAllText(notePath, BuildNotes(python), new UTF8Encoding(true));
        }
        catch (Exception e)
        {
            // Не страшно: программа уже на месте и запускается. Но
            // сказать надо, иначе человек потом не найдёт, чем
            // запустить, и не поймёт почему.
            Console.WriteLine("[ВНИМАНИЕ] не удалось создать run.bat: " +
                              e.Message);
            Console.WriteLine("Запустить можно вручную:");
            Console.WriteLine("  cd \"" + target + "\"");
            Console.WriteLine("  \"" + python + "\" -m allvpn.app");
        }

        Console.WriteLine();
        Console.WriteLine("Готово. Программа в папке:");
        Console.WriteLine("  " + target);
        Console.WriteLine();
        Console.WriteLine("Что дальше:");
        Console.WriteLine("  1. Запусти run.bat из этой папки.");
        Console.WriteLine("  2. Появится значок в трее справа внизу — это нормально.");
        Console.WriteLine("  3. Расширение для браузера лежит в папке extension:");
        Console.WriteLine("     chrome://extensions -> режим разработчика ->");
        Console.WriteLine("     «Загрузить распакованное расширение» -> выбери папку");
        Console.WriteLine("     extension внутри папки установки.");
        Console.WriteLine();
        Console.WriteLine("Подробности: INSTALL.txt рядом с run.bat");
        return 0;
    }

    // ------------------------------------------------------------- python

    /// <summary>Найти интерпретатор: сначала системный PATH.</summary>
    static string FindPython()
    {
        foreach (string name in new[] { "python", "py" })
        {
            try
            {
                var psi = new ProcessStartInfo(name, "-c \"import sys;print(sys.executable)\"")
                {
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    CreateNoWindow = true,
                };
                using (var p = Process.Start(psi))
                {
                    string outp = p.StandardOutput.ReadToEnd().Trim();
                    p.WaitForExit(20000);
                    if (p.ExitCode == 0 && File.Exists(outp)) return outp;
                }
            }
            catch { /* пробуем следующее имя */ }
        }

        // Запасной путь: обычная установка на C:.
        string guess = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs", "Python", "Python313", "python.exe");
        return File.Exists(guess) ? guess : null;
    }

    static bool PythonVersionOk(string python, out string version)
    {
        version = "неизвестна";
        string outp;
        if (!RunPython(python,
                "-c \"import sys;print('%d.%d'%sys.version_info[:2])\"", 30,
                out outp))
        {
            return false;
        }
        outp = outp.Trim();
        version = outp;
        string[] parts = outp.Split('.');
        int major = 0, minor = 0;
        if (parts.Length < 2) return false;
        if (!int.TryParse(parts[0], out major)) return false;
        if (!int.TryParse(parts[1], out minor)) return false;
        // 3.11 — первая версия, где есть всё, чем пользуется проект.
        return major > 3 || (major == 3 && minor >= 11);
    }

    // ------------------------------------------------------- скрипты для python

    /// <summary>Проверить, какие пакеты уже стоят. Печатает их имена.</summary>
    static string BuildCheckScript(KeyValuePair<string, string>[] packages)
    {
        var sb = new StringBuilder();
        sb.AppendLine("import importlib.util as u");
        sb.AppendLine("for name, mod in " + FormatPairs(packages) + ":");
        sb.AppendLine("    try:");
        sb.AppendLine("        u.find_spec(mod)");
        sb.AppendLine("        print(name)");
        sb.AppendLine("    except Exception:");
        sb.AppendLine("        pass");
        return sb.ToString();
    }

    /// <summary>Список пар как код Python: [(имя, модуль), ...].</summary>
    static string FormatPairs(KeyValuePair<string, string>[] pairs)
    {
        var sb = new StringBuilder();
        sb.Append("[");
        for (int i = 0; i < pairs.Length; i++)
        {
            if (i > 0) sb.Append(", ");
            sb.Append("('" + pairs[i].Key + "', '" + pairs[i].Value + "')");
        }
        sb.Append("]");
        return sb.ToString();
    }

    /// <summary>Проверить, что программа импортируется и готова к запуску.
    ///
    /// Проверяется ровно то, что нужно для работы: модули на месте,
    /// порт API тот, что ждёт расширение, и папка данных создаётся.
    /// Раньше здесь читался `config.VERSION`, которого в модуле нет:
    /// проверка падала с AttributeError на программе, которая в полном
    /// порядке. Проверять надо то, что действительно используется.
    /// </summary>
    static string BuildProbeScript()
    {
        return
            "import os, sys\n" +
            "sys.path.insert(0, r'.')\n" +
            "try:\n" +
            "    import allvpn.app, allvpn.config, allvpn.engine\n" +
            "    # Папка данных создаётся при первом запуске. Если её нет и\n" +
            "    # создать не удалось — работать будет не с чем.\n" +
            "    os.makedirs(allvpn.config.DATA_DIR, exist_ok=True)\n" +
            "    assert os.path.isdir(allvpn.config.DATA_DIR)\n" +
            "    print('модули на месте, API на порту %d' % allvpn.config.API_PORT)\n" +
            "except Exception as e:\n" +
            "    print('%s: %s' % (type(e).__name__, e))\n" +
            "    sys.exit(1)\n";
    }

    /// <summary>Папка, из которой запускается `python -m allvpn.app`.
    ///
    /// Это корень установки: пакет лежит в `installRoot\allvpn`, и
    /// Python ищет его рядом с рабочей папкой. Запуск из папки
    /// установщика дал бы «No module named allvpn».
    /// </summary>
    static string FindProgramDir(string installRoot)
    {
        return installRoot;
    }

    /// <summary>Найти папку пакета allvpn: вверх от установщика или рядом.
    ///
    /// Установщик может лежать в двух местах: рядом с папкой `allvpn`
    /// (обычная сборка в dist) или внутри распакованной программы. Ищем
    /// по признаку — папка с `__init__.py` и `app.py`, — а не по имени:
    /// имя папки в собранном варианте может быть любым.
    /// </summary>
    static string FindPackageDir()
    {
        // 1. Установщик запущен прямо из папки пакета.
        if (File.Exists(Path.Combine(Root, "__init__.py")) &&
            File.Exists(Path.Combine(Root, "app.py")))
        {
            return Root;
        }

        // 2. Рядом лежит папка allvpn.
        string beside = Path.Combine(Root, "allvpn");
        if (File.Exists(Path.Combine(beside, "__init__.py")))
        {
            return beside;
        }

        // 3. Уровнем выше: сборка могла положить exe в dist\allvpn,
        //    а исходники оставить в корне проекта.
        string up = Path.GetDirectoryName(
            Path.GetFullPath(Root).TrimEnd(Path.DirectorySeparatorChar));
        if (up != null)
        {
            string upPack = Path.Combine(up, "allvpn");
            if (File.Exists(Path.Combine(upPack, "__init__.py")))
            {
                return upPack;
            }
        }

        // 4. Перебор подпапок: ищем по содержимому, а не по имени.
        try
        {
            foreach (string dir in Directory.GetDirectories(Root))
            {
                if (File.Exists(Path.Combine(dir, "__init__.py")) &&
                    File.Exists(Path.Combine(dir, "app.py")))
                {
                    return dir;
                }
            }
        }
        catch { /* читать нечем — вернём null */ }

        return null;
    }

    static string BuildCmd(string python)
    {
        return "@echo off\r\n" +
               "chcp 65001 >nul\r\n" +
               "title AllVPN\r\n" +
               "cd /d \"%~dp0\"\r\n" +
               "echo Запуск AllVPN...\r\n" +
               "\"" + python + "\" -m allvpn.app\r\n" +
               "if errorlevel 1 (\r\n" +
               "    echo.\r\n" +
               "    echo Приложение завершилось с ошибкой.\r\n" +
               "    echo Подробности в allvpn\\data\\singbox.log\r\n" +
               "    pause\r\n" +
               ")\r\n";
    }

    /// <summary>Инструкция, остающаяся в папке установки.
    ///
    /// Пишется файлом, а не только печатается в консоль: окно
    /// установщика закроется, и человек останется с папкой без
    /// подсказки, что делать дальше.
    /// </summary>
    static string BuildNotes(string python)
    {
        return
            "AllVPN — как пользоваться\r\n" +
            "=======================\r\n" +
            "\r\n" +
            "ЗАПУСК\r\n" +
            "\r\n" +
            "  Двойной клик по run.bat.\r\n" +
            "\r\n" +
            "  После запуска в трее справа внизу появляется значок.\r\n" +
            "  Это нормально: окно можно закрыть, программа останется\r\n" +
            "  работать, пока не выключишь её через значок.\r\n" +
            "\r\n" +
            "  Если значка нет, а вы точно запускали — проверьте, что\r\n" +
            "  не закрыли окно консоли: пока оно открыто, программа\r\n" +
            "  работает.\r\n" +
            "\r\n" +
            "РАСШИРЕНИЕ ДЛЯ БРАУЗЕРА\r\n" +
            "\r\n" +
            "  Расширение лежит в папке extension рядом с этим файлом.\r\n" +
            "\r\n" +
            "  Chrome:\r\n" +
            "    1. Открой chrome://extensions\r\n" +
            "    2. Включи «Режим разработчика» (справа вверху)\r\n" +
            "    3. Нажми «Загрузить распакованное расширение»\r\n" +
            "    4. Выбери папку extension\r\n" +
            "\r\n" +
            "  Edge, Brave, Яндекс — то же самое, только адрес\r\n" +
            "  edge://extensions или brave://extensions.\r\n" +
            "\r\n" +
            "  Расширение управляет запущенной программой: если в\r\n" +
            "  попапе написано «AllVPN не запущен» — запусти run.bat.\r\n" +
            "\r\n" +
            "ЕСЛИ ЧТО-ТО НЕ РАБОТАЕТ\r\n" +
            "\r\n" +
            "  Лог ядра: allvpn\\data\\singbox.log\r\n" +
            "\r\n" +
            "  Состояние:  allvpn\\data\\state.json\r\n" +
            "\r\n" +
            "  Что установлено:\r\n" +
            "    \"" + python + "\" -m pip list\r\n" +
            "\r\n" +
            "УСТАНОВКА ЗАПИСАЛАСЬ\r\n" +
            "\r\n" +
            "  Python: " + python + "\r\n" +
            "\r\n" +
            "  Программа лежит в своей папке и больше ни от чего\r\n" +
            "  не зависит: её можно перенести целиком.\r\n";
    }

    // -------------------------------------------------------------- запуск

    /// <summary>Выполнить python с кодом. Печатает stdout+stderr.
    ///
    /// Код пишется во временный файл, а не передаётся аргументом:
    /// многострочный текст в аргументах Windows ломается — переносы
    /// строк превращаются в пробелы, и python получает не тот текст.
    /// Раньше установщик отдавал проверку пакетов как имя файла и
    /// получал «can't open file 'import'» вместо результата.
    /// </summary>
    static bool RunPython(string python, string args, int timeoutMs,
                          out string output)
    {
        return RunPythonIn(python, args, timeoutMs, Root, out output);
    }

    /// <summary>То же, но с явной рабочей папкой.</summary>
    static bool RunPythonIn(string python, string args, int timeoutMs,
                            string workDir, out string output)
    {
        output = "";

        // Код с переносами строк идёт во временный файл.
        string file = null;
        string realArgs = args;
        if (args.IndexOf('\n') >= 0 || args.IndexOf('\r') >= 0)
        {
            try
            {
                file = Path.Combine(Path.GetTempPath(),
                                    "allvpn_setup_" + Guid.NewGuid().ToString("N")
                                    + ".py");
                File.WriteAllText(file, args, Encoding.UTF8);
                realArgs = "\"" + file + "\"";
            }
            catch (Exception e)
            {
                output = "не удалось создать временный файл: " + e.Message;
                return false;
            }
        }

        try
        {
            var psi = new ProcessStartInfo(python, realArgs)
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
                WorkingDirectory = Directory.Exists(workDir) ? workDir : Root,
            };
            using (var p = Process.Start(psi))
            {
                string so = p.StandardOutput.ReadToEnd();
                string se = p.StandardError.ReadToEnd();
                if (!p.WaitForExit(timeoutMs))
                {
                    try { p.Kill(); } catch { }
                    output = so + se + "\n(превышено время ожидания)";
                    return false;
                }
                output = so + se;
                return p.ExitCode == 0;
            }
        }
        catch (Exception e)
        {
            output = e.Message;
            return false;
        }
        finally
        {
            if (file != null)
            {
                try { File.Delete(file); } catch { }
            }
        }
    }

    // -------------------------------------------------------------- копии

    /// <summary>Лежит ли путь внутри папки назначения.</summary>
    static bool IsInsideTarget(string path, string targetFull)
    {
        string full = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar);
        return full.StartsWith(targetFull + Path.DirectorySeparatorChar,
                               StringComparison.OrdinalIgnoreCase);
    }

    static void CopyTree(string from, string to, ref int copied, string targetFull)
    {
        Directory.CreateDirectory(to);
        foreach (string file in Directory.GetFiles(from))
        {
            // Файл тоже может оказаться внутри папки назначения, если
            // копирование пошло вглубь по-настоящему.
            if (IsInsideTarget(file, targetFull)) continue;
            File.Copy(file, Path.Combine(to, Path.GetFileName(file)), true);
            copied++;
        }
        foreach (string dir in Directory.GetDirectories(from))
        {
            string name = Path.GetFileName(dir);
            // Вложенные кэши пропускаем тоже: они появляются при первом
            // же запуске, а места занимают прилично.
            if (name == "__pycache__") continue;
            // Главная защита: рекурсия не должна заходить туда, откуда
            // мы копируем. Без неё папка копируется сама в себя, путь
            // растёт с каждым шагом, и Windows обрывает всё ошибкой
            // «путь слишком длинный» — без указания, что именно сломано.
            if (IsInsideTarget(dir, targetFull)) continue;
            CopyTree(dir, Path.Combine(to, name), ref copied, targetFull);
        }
    }

    /// <summary>Записать папку назначения в лог для разбора.</summary>
    static void WriteInstallLog(string path, string text)
    {
        try
        {
            File.WriteAllText(path, text, Encoding.UTF8);
        }
        catch { /* лог — вспомогательное, падать из-за него нельзя */ }
    }

    static void Fail(string message)
    {
        Console.Error.WriteLine("[ОШИБКА] " + message);
    }
}
