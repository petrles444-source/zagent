# Поднять Аду на PythonAnywhere: что вписать в консоль

Дата: 8 октября 2026. Токен бота `@adaweffeBot` проверен — он рабочий.
Ключ провайдера модели на сервере надо проверить: без него бот
поднимется, но на первое сообщение ответит «провайдер не настроен».

---

## Сначала честно: что консоль может и что не может

На бесплатном тарифе PythonAnywhere нет постоянных задач — это
проверено, `постоянных задач: 0`. Консоль — интерактивная: она живёт,
пока открыта вкладка браузера. Закрыли вкладку — бот умер.

Поэтому консоль годится для проверки: убедиться, что код запускается,
модель отвечает и бот пишет в Telegram. Для работы круглосуточно
консоль не подходит, и это не вопрос настройки.

Второй путь — веб-приложение: оно живёт постоянно, и `wsgi.py` уже
запускает бота в фоновом потоке. Но сейчас приложение отдаёт
«Hello, World!», то есть сервер не подхватывает `wsgi.py`. Если
команда 6 покажет, что файл на месте и в нём есть `application`,
значит остаётся указать путь к скрипту в веб-интерфейсе
(`Web → Edit → Code`).

---

## Команды

Вставляйте по одной, в консоли PythonAnywhere
(`https://www.pythonanywhere.com/user/HostMoon6/consoles/`).
Вкладку не закрывайте, пока идёт проверка.

### 1. Зайти в папку и убедиться, что всё на месте

```bash
cd /home/HostMoon6/zstatus && ls -la
```

Ожидаемый ответ: `ada_bot.py`, `linda_bot.py`, `persona.py`,
`user_features.py`, `show_self.py`, `wsgi.py`, `config.json`,
папка `pictures`.

### 2. Проверить, что токен в настройках есть

```bash
python3 -c "import json;d=json.load(open('config.json'));print('токен:', 'есть' if d.get('telegram_token') else 'ПУСТО');print('провайдеров:', len(d.get('providers') or []));print('ключи:', [(p.get('name'), 'есть' if p.get('api_key') else 'ПУСТО') for p in d.get('providers') or []])"
```

Ожидаемый ответ: `токен: есть` и хотя бы один провайдер с
`ключ: есть`.

Если токена нет — впишите его командой 3. Если ключа нет — командой 4.

### 3. Вписать токен бота

```bash
python3 -c "import json;d=json.load(open('config.json'));d['telegram_token']='СЮДА_ТОКЕН';json.dump(d,open('config.json','w'),ensure_ascii=False,indent=2);print('токен записан')"
```

Токен: `8552619734:AAEGUNIs04CmXzO4a48xeC22XjxO1pOEbJU`

**Осторожно:** токен окажется в истории команд консоли. После того как
заработает, перевыпустите его у @BotFather через `/revoke` и впишите
новый — так он перестанет быть засвеченным.

### 4. Вписать ключ модели

```bash
python3 -c "import json;d=json.load(open('config.json'));p=d['providers'][0];p['api_key']='СЮДА_КЛЮЧ';json.dump(d,open('config.json','w'),ensure_ascii=False,indent=2);print('ключ записан для', p.get('name'))"
```

Ключ OpenRouter лежит у вас в `config/secrets.local.json`. Если
провайдеров несколько, номер после квадратных скобок — индекс
нужного, считая с нуля.

### 5. Проверить, что до модели вообще можно достучаться

Это самая частая причина молчания: PythonAnywhere часть адресов
не пускает, и бот падает на первом же запросе.

```bash
python3 -c "
import json,urllib.request
d=json.load(open('config.json'))
p=d['providers'][d.get('active') or 0]
body=json.dumps({'model':p.get('model'),'messages':[{'role':'user','content':'Скажи одно слово: да'}],'max_tokens':10}).encode()
r=urllib.request.Request(p['base_url'].rstrip('/')+'/chat/completions',data=body,headers={'Authorization':'Bearer '+p['api_key'],'Content-Type':'application/json','HTTP-Referer':'https://zagent.do.am/'})
try:
    print('ответ:', json.loads(urllib.request.urlopen(r,timeout=90).read())['choices'][0]['message']['content'][:60])
except Exception as e:
    print('НЕ ДОШЛО:', type(e).__name__, str(e)[:200])
"
```

Ожидаемый ответ: `ответ: да` или любой короткий текст.
Если `НЕ ДОШЛО: HTTP Error 401` — ключ неверный или истёк.
Если `HTTP Error 403` — хостинг не пускает на этот адрес, нужен другой
провайдер.

### 6. Проверить, что Telegram отдаёт обновления

```bash
python3 -c "import json,urllib.request;d=json.load(open('config.json'));t=d['telegram_token'];u=f'https://api.telegram.org/bot{t}/getUpdates?timeout=3';j=json.loads(urllib.request.urlopen(u,timeout=30).read());print('ok' if j['ok'] else 'отказ');print('обновлений:',len(j.get('result',[])))"
```

Ожидаемый ответ: `ok`. Если `Conflict: terminated by other getUpdates`
— бот уже запущен где-то ещё, его надо остановить.

### 7. Запустить бота

```bash
python3 -u ada_bot.py 2>&1 | tee -a bot.log
```

Ключи: `-u` — вывод без буферизации, иначе в консоли ничего не видно
до конца строки. `tee -a` — пишем в журнал, чтобы после закрытия
вкладки было видно, чем закончилось.

Ожидаемый ответ: строка вида «бот слушает сообщения».

**Теперь напишите боту в Telegram.** Он должен ответить.

### 8. Если не отвечает — посмотреть причину

```bash
tail -n 40 bot.log
```

Смотрите на последнюю строку с ошибкой.

---

## Если бот запустился, но в группе молчит

Проверено через API: у бота выключена приватность
(`can_read_all_group_messages: false`). В группах он видит только
команды с упоминанием. Отключается у @BotFather:

```
/setprivacy
```
выбрать бота → `Disable`

После этого перезапустите бота.

---

## Если консоль закрылась — бот умер

Это ожидаемо, а не поломка. Дальше два пути.

**Путь 1: веб-приложение.** Оно живёт постоянно, и `wsgi.py` уже
поднимает бота в фоновом потоке. Проблема в том, что сервер не
подхватывает скрипт. Проверьте, что файл цел:

```bash
grep -c "application" wsgi.py && python3 -c "import ast;ast.parse(open('wsgi.py').read());print('wsgi.py разбирается')"
```

Если обе строки прошли, осталось указать путь в веб-интерфейсе:
`Web` → выбрать приложение → `Edit` → в поле **Code** вписать
`/home/HostMoon6/zstatus/wsgi.py` → `Reload`. После этого
`https://HostMoon6.pythonanywhere.com/healthz` должен ответить `ok`.

**Путь 2: вебхук на бесплатном хостинге.** Бот не должен жить
постоянно — Telegram сам приходит по адресу. Готовый файл
`bot-worker/worker.js` лежит в проекте; ему нужны только два
секрета и один адрес Cloudflare. Подробности — в шапке файла.

---

## Что прислать мне, если что-то не сработает

Текст ошибки из `tail -n 40 bot.log` и строку с кодом из шага 5.
Больше ничего не нужно: остальное я проверю сам.
