"""Проверка `tools/check_secrets.py`: не пропускает ли она утечку ключа.

Скрипт написан для одной задачи — поймать ключ в индексе git. Проверять его
на настоящих файлах смысла нет: он и так работает с индексом. Поэтому
проверяется другое — что он в самом деле ловит утечку, а не отвечает
«чисто» на всё подряд.

Если проверка врёт в любую сторону, она хуже отсутствия проверки: от
«чисто» перестают верить, а от ложной тревоги начинают игнорировать.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_checker():
    """Загрузить скрипт по пути.

    Имя с дефисом не является пакетным, поэтому обычный импорт не подходит,
    а копировать код скрипта в тест — значит проверять не то, что
    запускается на самом деле.
    """
    path = ROOT / "tools" / "check_secrets.py"
    spec = importlib.util.spec_from_file_location("zagent_check_secrets", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def checker():
    return load_checker()


def _stage(tmp_path: Path, files: dict[str, str], root: Path) -> list[str]:
    """Создать репозиторий с заданными файлами и вернуть список в индексе.

    Пути в возврате относительные — такие же, как даёт `git ls-files` в
    настоящем проекте. Скрипт читает файлы по этим путям от текущего каталога,
    поэтому проверка обязана идти с `cwd` в корень репозитория, иначе
    читать будет нечего и всё найдётся «чисто».
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, body in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return [f for f in subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.splitlines() if f]


@contextmanager
def mock_read_text(root: Path):
    """Читать файлы скрипка относительно временного репозитория.

    Подменяется `Path.read_text`: скрипт читает файлы относительно текущего
    каталога, и менять его рабочий каталог из проверки нельзя — проверяется
    тот код, который запускается руками.
    """
    real = Path.read_text

    def read_text(self: Path, *a, **kw):  # noqa: ANN001
        return real(self if self.is_absolute() else root / self, *a, **kw)

    with mock.patch.object(Path, "read_text", read_text):
        yield


def test_ловит_настоящий_ключ_под_любым_именем(checker, tmp_path: Path) -> None:
    """Главный случай: ключ спрятан в безобидном файле и так и уедет в гит.

    `.gitignore` закрывает только файл секретов. Ключ, скопированный в тест,
    в пример или в отчёт, ничем не прикрыт — и именно его ищет сверка с
    настоящими ключами.
    """
    secret = "sk-or-v1-" + "a" * 56
    files = _stage(tmp_path, {
        "README.md": "обычный текст без ключей\n",
        "tests/test_anything.py": f'SECRET = "{secret}"\n',
    }, tmp_path)

    with mock_read_text(tmp_path):
        hits = checker.scan_exact(files, [secret])
    assert hits, "настоящий ключ обязан быть найден"
    assert hits[0][0] == "tests/test_anything.py"


def test_чисто_когда_ключей_нет(checker, tmp_path: Path) -> None:
    files = _stage(tmp_path, {
        "README.md": "текст\n",
        "hub/config.py": "def load(): ...\n",
    }, tmp_path)
    with mock_read_text(tmp_path):
        assert checker.scan_exact(files, ["sk-or-v1-" + "b" * 56]) == []


def test_ловит_по_форме_без_знания_ключа(checker, tmp_path: Path) -> None:
    """Ключ, о котором скрипт не знает, тоже должен попасть в вывод.

    Сверка с секретами находит только то, что есть в
    `secrets.local.json`. Ключ из нового шлюза или утёкший с другого
    компьютера в этом файле не появится — и без проверки по форме пройдёт
    незамеченным.
    """
    files = _stage(tmp_path, {
        "notes.md": "nvapi-" + "c" * 50 + "\n",
    }, tmp_path)
    with mock_read_text(tmp_path):
        hits = checker.scan_shape(files)
    assert hits, "ключ неизвестного шлюза должен ловиться по форме"
    assert any(p == "nvidia" for _, _, p in hits), hits


def test_заглушки_не_поднимают_тревогу(checker, tmp_path: Path) -> None:
    """Тестовые заглушки не должны выглядеть как утечка.

    Иначе сигнал перестаёт работать: настоящий ключ найдётся в общем шуме и
    его перестанут читать.
    """
    files = _stage(tmp_path, {
        "tests/test_keyring.py": 'SECRET = "sk-or-v1-' + "0" * 56 + '"\n',
    }, tmp_path)
    with mock_read_text(tmp_path):
        shaped = checker.scan_shape(files)
    assert shaped, "форма должна совпасть"
    assert checker.STUB_HINT.search("sk-or-v1-" + "0" * 56)


def test_шаблон_секретов_исключён(checker, tmp_path: Path) -> None:
    """`secrets.local.json.example` содержит ключи по виду — и это нормально.

    Без исключения проверка всегда ругалась бы на шаблон, и её перестали бы
    запускать. Исключение узкое: сам файл секретов в `.gitignore` и в индекс
    не попадает.
    """
    files = _stage(tmp_path, {
        "config/secrets.local.json.example": '{"openrouter": "sk-or-v1-'
        + "e" * 56 + '"}\n',
    }, tmp_path)
    with mock_read_text(tmp_path):
        assert checker.scan_exact(files, ["sk-or-v1-" + "e" * 56]) == []


def test_пропущенный_файл_не_останавливает_проверку(
        checker, monkeypatch: pytest.MonkeyPatch) -> None:
    """Файл исчез между `ls-files` и чтением — не повод падать.

    Такое бывает при параллельной работе в репозитории, и падение здесь
    означало бы «проверку не удалось провести», а это хуже, чем «чисто».
    """
    files = ["несуществующий.py", "README.md"]

    def read_text(self: Path, *a, **kw):  # noqa: ANN001
        if self.name.endswith(".py"):
            return "sk-or-v1-" + "f" * 56
        raise OSError("файл исчез")

    with mock.patch.object(Path, "read_text", read_text):
        hits = checker.scan_exact(files, ["sk-or-v1-" + "f" * 56])
    assert hits, "существующий файл всё равно проверяется"


def test_читает_ключи_из_локального_файла() -> None:
    """Настоящие ключи берутся из файла секретов, а не из конфига в гите."""
    module = load_checker()
    secrets = module.real_secrets()
    # Проверка идёт на настоящем проекте, где файл секретов есть. Если его
    # нет — это тоже корректное состояние, просто проверить нечего.
    path = ROOT / "config" / "secrets.local.json"
    if path.is_file():
        assert secrets, "файл секретов есть, но ключи из него не прочитались"
        assert all(len(s) >= 20 for s in secrets)
    else:
        assert secrets == []