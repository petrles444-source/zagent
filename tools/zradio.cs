// zradio.exe — точка входа CLI-клиента радио.
//
// Ищет .venv рядом с собой и запускает tools\zradio.py тем же python.
// Если .venv нет — пробует python из PATH. При неудаче печатает
// подсказку и возвращает код 1.
//
// Сборка:
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /out:zradio.exe tools\zradio.cs

using System;
using System.Diagnostics;
using System.IO;
using System.Text;

static class ZRadioLauncher
{
    static int Main(string[] args)
    {
        // Каталог, где лежит exe (корень проекта)
        string root = Path.GetDirectoryName(
            Path.GetFullPath(System.Reflection.Assembly.GetExecutingAssembly().Location));

        // Ищем python: сначала .venv, потом PATH
        string py = Path.Combine(root, ".venv", "Scripts", "python.exe");
        if (!File.Exists(py))
        {
            py = "python";
        }

        string script = Path.Combine(root, "tools", "zradio.py");
        if (!File.Exists(script))
        {
            Console.Error.WriteLine("не найден tools\\zradio.py");
            return 1;
        }

        // Собираем командную строку
        StringBuilder sb = new StringBuilder();
        sb.Append('"').Append(script).Append('"');
        foreach (string a in args)
        {
            sb.Append(' ').Append('"').Append(a.Replace("\"", "\\\"")).Append('"');
        }

        ProcessStartInfo psi = new ProcessStartInfo
        {
            FileName = py,
            Arguments = sb.ToString(),
            UseShellExecute = false,
        };

        try
        {
            using (Process p = Process.Start(psi))
            {
                p.WaitForExit();
                return p.ExitCode;
            }
        }
        catch (Exception e)
        {
            Console.Error.WriteLine("не удалось запустить python: " + e.Message);
            return 1;
        }
    }
}
