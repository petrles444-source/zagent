"""Проверка Ады прямо на сервере: конфиг, персона и вызов модели.

Отдельный запуск нужен потому, что бот в фоне ест обновления сам:
подставить ему сообщение снаружи нельзя. Здесь проверяется ровно та
часть, которая на сервере отличается от домашней: чтение config.json
и поход в провайдера через прокси хостинга.

Запуск на сервере:  python3 selfcheck.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ada_bot as ada  # noqa: E402


def main() -> int:
    config = ada.load_config()
    print("1. конфиг прочитан")
    print(f"   токен: {'есть' if config['token'] else 'НЕТ'}")
    print(f"   провайдеров: {len(config['providers'])}")
    print(f"   персона: {len(config['persona'])} символов")
    if not config["token"]:
        print("   БЕЗ ТОКЕНА — бот не сможет отвечать")
        return 1
    if not config["providers"]:
        print("   БЕЗ ПРОВАЙДЕРОВ — отвечать нечем")
        return 1

    # Имя ловится?
    for word in ("Ада", "ada", "ADA Ada"):
        print(f"2. «{word}» вызывает бота:", bool(ada.NAME_TRIGGERS.search(word)))
    for word in ("адаптер", "палата"):
        print(f"   «{word}» НЕ вызывает:", not ada.NAME_TRIGGERS.search(word))

    # Правило десятого сообщения.
    ada.CHATS.clear()
    sent = []
    ada.send = lambda token, chat, text: sent.append(chat)
    for number in range(1, 11):
        ada.handle(config, {"chat": {"id": 1, "type": "group"},
                            "from": {"id": 5, "first_name": "Иван"},
                            "text": f"реплика {number}"})
    print(f"3. из 10 реплик в беседе бот вмешался {len(sent)} раз (ожидаем 1)")

    # Настоящий вызов модели: тут падает всё, что не работает с сетью.
    # Проверяем ВСЕ провайдеры подряд: с сервера доступ может быть закрыт
    # ровно у одного из них (Groq отвечает 403 по региону исходящих
    # адресов), а домашняя машина ходит туда свободно.
    print("4. спрашиваю модели по-настоящему…")
    ada.CHATS[1]["history"].append(("Иван", "Привет! Ты кто?"))
    prompt = ada.build_prompt(ada.CHATS[1])
    working = []
    for provider in config["providers"]:
        try:
            answer = ada.ask_model(provider, prompt, config["persona"])
        except Exception as exc:
            print(f"   {provider['name']:14} НЕ РАБОТАЕТ: {exc}")
            continue
        if answer:
            print(f"   {provider['name']:14} работает, ответ: {answer[:150]}")
            working.append(provider["name"])
        else:
            print(f"   {provider['name']:14} ответ пустой")
    print(f"\n5. рабочих провайдеров: {len(working)} — "
          f"{', '.join(working) or 'ни одного'}")
    return 0 if working else 1


if __name__ == "__main__":
    sys.exit(main())
