r"""Выложить бота на PythonAnywhere: файлы, веб-приложение, запуск.

Запуск:
    .venv\Scripts\python.exe hosting\pythonanywhere\deploy.py --check
    .venv\Scripts\python.exe hosting\pythonanywhere\deploy.py --upload
    .venv\Scripts\python.exe hosting\pythonanywhere\deploy.py --webapp
    .venv\Scripts\python.exe hosting\pythonanywhere\deploy.py --all

`--check` ничего не меняет и показывает, что вообще можно: остаток
CPU, список веб-приложений и фоновых задач. С него и начинают, потому
что на бесплатном тарифе часть действий закрыта подпиской, и лучше
узнать об этом до заливки файлов.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from pa_api import PaError, PythonAnywhere, load_credentials  # noqa: E402

BOTS = HERE / "bots"
#: Что уезжает на сервер. `config.json` здесь нет намеренно: настоящие
#: ключи заливаются отдельно и живут только на сервере.
#:
#: Список полный не из симпатии к спискам, а потому что `ada_bot.py`
#: импортирует `persona.py` и `user_features.py` на верхнем уровне: без
#: них на сервере ImportError, и бот не поднимется вообще. `wsgi.py`
#: запускает бота в фоне, `show_self.py` умеет слать картинки.
#:
#: `linda_bot.py` добавлен вторым ботом. Его в списке не было, и
#: выкладка рапортовала об успехе: Ада заливалась, Линда — нет, то
#: есть половина работы уходила на сервер молча. Список на глаз
#: расходится с содержимым папки при каждом новом файле, поэтому
#: правильнее сверять каталог: см. `check_upload_list`.
UPLOAD_NAMES = (
    "wsgi.py",
    "ada_bot.py",
    "linda_bot.py",
    "persona.py",
    "user_features.py",
    "show_self.py",
    "config.example.json",
    # Три файла добавлены при переходе на трёх ботов. Без них сервер
    # падал бы на импорте: `ada_bot.py` теперь тянет `chars.py`, а
    # `run_all.py` без `bots.json` не знает, кого запускать.
    #
    # Раньше выкладка об этом не предупреждала: список составлялся на
    # глаз и молча разошёлся с содержимым папки. Теперь
    # `check_upload_list` сверяет каталог и кричит, если что-то забыто.
    "chars.py",
    "run_all.py",
    "bots.json",
)

#: Картинки из pictures/ — по всей папке, а не поштучно: список имён
#: разъезжался бы с содержимым при каждом новом файле.
PICTURES_SUBDIR = "pictures"


def show_check(pa: PythonAnywhere) -> int:
    """Показать состояние аккаунта без изменений."""
    try:
        cpu = pa.cpu()
    except PaError as exc:
        print(f"квота: недоступно ({exc})")
    else:
        used = float(cpu.get("daily_cpu_total_usage_seconds") or 0)
        limit = int(cpu.get("daily_cpu_limit_seconds") or 0)
        print(f"квота CPU: {used:.1f} из {limit} с "
              f"({100 * used / limit:.0f}% расходовано)")
        print(f"сброс: {cpu.get('next_reset_time')}")
    try:
        apps = pa.webapps() or []
        print(f"веб-приложений: {len(apps)}")
        for app in apps:
            # Печатаем `source_directory`, а не `code`. Поля `code` в
            # ответе API не существует — оно пришло из UI и в JSON не
            # попало. Из-за этого отчёт годами показывал `код=None`
            # и очень уверенно намекал, что код не задан. Он был
            # задан: `/home/HostMoon6/zstatus` стоял как надо, а сайт
            # отдавал заглушку по другой причине. Ложный диагноз
            # хуже отсутствия диагноза — он уводит не туда.
            print(f"   {app.get('domain_name')}")
            print(f"      каталог кода: {app.get('source_directory')}")
            print(f"      рабочий каталог: {app.get('working_directory')}")
            print(f"      python: {app.get('python_version')}, "
                  f"HTTPS: {app.get('force_https')}, "
                  f"включено: {app.get('enabled')}")
            if not app.get("source_directory"):
                print("      ВНИМАНИЕ: каталог кода не задан — приложение "
                      "будет отдавать заглушку. Задайте его: "
                      "deploy.py --webapp")
    except PaError as exc:
        print(f"веб-приложения: {exc}")
    try:
        tasks = pa.always_on() or []
        print(f"постоянных задач: {len(tasks)} "
              f"(на бесплатном тарифе обычно недоступно)")
    except PaError as exc:
        print(f"постоянные задачи: {exc}")
    return 0


def check_upload_list() -> int:
    """Сверить `UPLOAD_NAMES` с содержимым папки `bots`.

    Список написан руками, и это его слабое место: в папке появился
    второй бот, а в список — нет. Выкладка отчиталась об успехе,
    половина файлов на сервер не уехала, и никто этого не заметил,
    потому что сообщение было зелёным.

    Теперь расхождение видно до выкладки: любой `.py` в папке, который
    не назван в списке, попадает в отчёт. Логи с сервера и `bot.log`
    в список не идут — они создаются на сервере сами.
    """
    # Сверяем и `.py`, и те файлы, что перечислены поимённо: список
    # может содержать `.json` (схема ключей), а обход только по `*.py`
    # объявил бы нормальный файл отсутствующим. Раньше он так и
    # объявлял — проверка врала на живом проекте.
    listed = set(UPLOAD_NAMES)
    on_disk = {p.name for p in BOTS.glob("*.py")
               if not p.name.startswith("_")}
    on_disk |= {name for name in listed if name.endswith(".json")}
    problems = 0

    for name in sorted(on_disk - listed):
        print(f"  НЕ ЗАГРУЖАЕТСЯ: {name} — есть в bots/, нет в UPLOAD_NAMES")
        problems += 1
    for name in sorted(listed - on_disk):
        print(f"  НЕТ ФАЙЛА: {name} — указан в UPLOAD_NAMES, но его нет")
        problems += 1

    if not problems:
        print(f"  список совпадает с папкой: {len(listed)} файл(ов)")
    return problems


def do_upload(pa: PythonAnywhere, remote_dir: str) -> int:
    """Залить файлы бота."""
    for name in UPLOAD_NAMES:
        local = BOTS / name
        if not local.is_file():
            print(f"нет файла {local.name}")
            return 1
        pa.upload_file(f"{remote_dir}/{name}", local)
        print(f"залит {remote_dir}/{name}  ({local.stat().st_size} байт)")

    # Картинки отдельным проходом: папка может отсутствовать, и это не
    # повод отменять выкладку кода — бот запустится и без них.
    pictures = BOTS / PICTURES_SUBDIR
    if pictures.is_dir():
        shots = sorted(p for p in pictures.iterdir()
                       if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
        for shot in shots:
            pa.upload_file(f"{remote_dir}/{PICTURES_SUBDIR}/{shot.name}", shot)
            print(f"залит {PICTURES_SUBDIR}/{shot.name}  "
                  f"({shot.stat().st_size} байт)")
        if not shots:
            print(f"{PICTURES_SUBDIR}/ пуста — картинок не будет")
    else:
        print(f"нет папки {PICTURES_SUBDIR} — картинок не будет")

    print("\nТеперь на сервере нужен config.json с ключами. Схема:")
    print(f"  {BOTS / 'config.example.json'}")
    print("Залить его можно так:")
    print(f"  deploy.py --put-config {remote_dir}/config.json")
    print("Либо одной командой, ключи берутся из config/secrets.local.json")
    print("и в памяти скрипта:")
    print("  make_bot_config.py")
    return 0


def do_put_config(pa: PythonAnywhere, remote_path: str) -> int:
    """Залить config.json из локальной копии.

    Локальный источник — `bots/config.local.json`; он в .gitignore,
    и это единственное место, где ключи лежат на диске этой машины.
    """
    local = BOTS / "config.local.json"
    if not local.is_file():
        print(f"Нет {local.name}. Скопируйте config.example.json и впишите "
              "токен бота и ключи провайдеров.")
        return 1
    data = json.loads(local.read_text(encoding="utf-8"))
    missing = [p.get("name") for p in data.get("providers", [])
               if p.get("api_key") and "ВПИШИТЕ" in str(p.get("api_key"))]
    if missing:
        print(f"В ключах остались пометки вместо значений: {', '.join(missing)}")
        return 1
    pa.upload_file(remote_path, local)
    print(f"залит {remote_path}")
    return 0


def do_webapp(pa: PythonAnywhere, domain: str, remote_dir: str,
              python_version: str) -> int:
    """Создать веб-приложение и перезапустить его.

    При повторном запуске приложение уже существует, и попытка создать
    его снова даёт HTTP 400. Раньше это печаталось как ошибка, хотя
    ничего плохого не случилось: человек видел страшное сообщение
    после каждой выкладки и думал, что заливка сорвалась.

    Теперь наличие проверяется заранее, и «уже есть» — обычный ход
    дела, а не тревога.
    """
    existing = {str(app.get("domain_name") or app.get("domain") or "")
                for app in (pa.webapps() or [])}
    if domain in existing:
        print(f"веб-приложение {domain} уже есть — создавать не нужно")
    else:
        try:
            pa.create_webapp(domain, python_version)
            print(f"создано веб-приложение {domain}")
        except PaError as exc:
            print(f"создание не вышло: {exc}")

    try:
        pa.webapp_configure(domain, source_directory=remote_dir,
                            force_https=True)
        print("каталог кода и HTTPS заданы")
    except PaError as exc:
        print(f"настройка: {exc}")
    try:
        pa.webapp_reload(domain)
        print("перезапущено")
    except PaError as exc:
        print(f"перезапуск: {exc}")
    print(f"\nАдрес: https://{domain}/")
    print("Это веб-приложение: по нему отвечает HTTP-сторона. Сам бот")
    print("работает фоновой задачей, а не через веб.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="выкладка бота на PythonAnywhere")
    parser.add_argument("--check", action="store_true", help="показать состояние")
    parser.add_argument("--upload", action="store_true", help="залить файлы бота")
    parser.add_argument("--put-config", metavar="REMOTE", help="залить config.json")
    parser.add_argument("--webapp", action="store_true", help="создать веб-приложение")
    parser.add_argument("--all", action="store_true", help="check + upload + webapp")
    args = parser.parse_args()
    if not any([args.check, args.upload, args.put_config, args.webapp, args.all]):
        args.check = True

    try:
        cfg = load_credentials()
    except PaError as exc:
        print(exc)
        return 2
    pa = PythonAnywhere(cfg)
    remote_dir = cfg.get("remote_dir", f"/home/{cfg['username']}/zstatus")
    domain = cfg.get("webapp_domain", f"{cfg['username']}.pythonanywhere.com")
    version = cfg.get("python_version", "python3.11")

    if args.check or args.all:
        show_check(pa)
        print()
        print("сверка списка выкладки с папкой bots:")
        check_upload_list()
    if args.upload or args.all:
        print()
        if do_upload(pa, remote_dir):
            return 1
    if args.put_config:
        print()
        if do_put_config(pa, args.put_config):
            return 1
    if args.webapp or args.all:
        print()
        do_webapp(pa, domain, remote_dir, version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
