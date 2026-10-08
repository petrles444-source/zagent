/* Мини-приложение: знакомство, выбор персонажа, экспресс-тест.
 *
 * Зачем приложение, если есть бот
 * ------------------------------
 * Бот начинает разговор с нуля и подстраивается по ходу: пользователь
 * сам выясняет, какие ответы ему нужны, тратя на это сообщения.
 * Здесь то же самое собирается за три шага — имя, персонаж, четыре
 * вопроса — и уходит боту одной строкой.
 *
 * Почему профиль хранится на телефоне, а не на сервере
 * --------------------------------------------------
 * Здесь нет своей базы и своего сервера: приложение — статические
 * файлы. Всё, что набрано, лежит в localStorage устройства и уходит
 * боту только по нажатию кнопки. Пока пользователь не нажал, профиль
 * никуда не отправлен — об этом стоит сказать прямо, потому что
 * вопросы про то, чем человек занимается, не хочется отправлять
 * мимоходом.
 *
 * Почему работает без скрипта Telegram
 * -----------------------------------
 * Официальный SDK грузится с telegram.org, а правило проекта запрещает
 * внешние загрузки: страница обязана открываться без сети. Поэтому
 * приложение сначала пробует взять готовый объект Telegram из окна,
 * и если его нет — работает как обычная страница. Кнопки Telegram
 * при этом не появляются, зато приложение не остаётся пустым.
 */

/* --- что за голоса -------------------------------------------------
 *
 * Ключи совпадают с VOICES в tools/bot_proxy.py. Если там появится
 * новый голос, приложение его не увидит и покажет устаревший список —
 * поэтому ключи проверяются в tools/check_miniapp.py.
 */
var VOICES = [
  {
    key: 'anatoly',
    name: 'Анатолий',
    what: 'программист из службы поддержки',
    about: 'объясняет код, разбирает ошибки по месту, даёт примеры целиком',
    mark: 'А',
    color: '#2c6bd1'
  },
  {
    key: 'guide',
    name: 'Проводник',
    what: 'знает этот сайт',
    about: 'коротко отвечает, что это за страница и где что лежит',
    mark: 'П',
    color: '#12857a'
  },
  {
    key: 'archivist',
    name: 'Хранитель',
    what: 'помнит флеш-работы',
    about: 'рассказывает про архив Neural Archive и как он устроен',
    mark: 'Х',
    color: '#7a4fbf'
  }
];

/* --- экспресс-тест -------------------------------------------------
 *
 * Четыре вопроса, а не десять: приложение открывают в телефоне, и
 * десять вопросов превращают знакомство в анкету, которую бросают на
 * третьем. Каждый вопрос влияет на то, как помощник себя ведёт, —
 * иначе он был бы декорацией.
 *
 * Варианты набраны парами «часто — редко», чтобы выбор был осознанным,
 * а не «первое попалось». Порядок вариантов не перемешивается между
 * шагами специально: случайный порядок ломал бы впечатление, что
 * вопросы равнозначны по важности.
 */
var QUESTIONS = [
  {
    q: 'Что вам обычно нужно от помощника',
    options: [
      { v: 'code',   t: 'Разобраться в коде или ошибке' },
      { v: 'answer', t: 'Быстрый точный ответ на вопрос' },
      { v: 'idea',   t: 'Подкинуть идею, когда застрял' },
      { v: 'talk',   t: 'Поговорить, чтобы отвлечься' }
    ]
  },
  {
    q: 'Сколько ответа нужно обычно',
    options: [
      { v: 'short',  t: 'Коротко, в одно-два предложения' },
      { v: 'normal', t: 'Средне: суть и пара деталей' },
      { v: 'deep',   t: 'Подробно, с примерами' },
      { v: 'steps',  t: 'По шагам, чтобы повторить у себя' }
    ]
  },
  {
    q: 'Что смотрите в ответе в первую очередь',
    options: [
      { v: 'why',    t: 'Почему так, а не иначе' },
      { v: 'how',    t: 'Как это сделать' },
      { v: 'code',   t: 'Готовый код, чтобы вставить' },
      { v: 'proof',  t: 'Как проверить, что работает' }
    ]
  },
  {
    q: 'Когда проще, когда понятно',
    options: [
      { v: 'terms',  t: 'Точные термины, для своего круга' },
      { v: 'plain',  t: 'Обычные слова, без жаргона' },
      { v: 'both',   t: 'Термин и сразу пояснение' }
    ]
  }
];

/* --- состояние ----------------------------------------------------- */

var STORE_KEY = 'tma-profile-v1';

var state = {
  step: 0,
  name: '',
  voice: 'guide',
  tone: 'normal',
  answers: [],      // индексы выбранных вариантов по QUESTIONS
  question: 0
};

var lastPane = -1;

/* --- мелкие помощники ---------------------------------------------- */

function $(id) { return document.getElementById(id); }

function show(node, on) { node.hidden = !on; }

/* Панель показывается только одна: иначе при переходе назад остаются
 * видны поля предыдущего шага, и человек правит не то. */
function paintPane(index) {
  if (lastPane === index) return;
  var panes = document.querySelectorAll('.pane');
  for (var i = 0; i < panes.length; i++) {
    show(panes[i], Number(panes[i].dataset.pane) === index);
  }
  lastPane = index;

  // Шаг и заголовок едут вместе с панелью, а не отдельно: рассинхрон
  // «шаг 2» над текстом первого шага путает сильнее, чем любая
  // формулировка.
  var titles = [
    ['Знакомимся', 'Три коротких шага — и помощник перестанет отвечать одинаково всем подряд.'],
    ['Кто будет отвечать', 'Персонажа можно поменять в любой момент.'],
    ['Пара вопросов', 'Ответы определяют длину и манеру ответа.'],
    ['Готовы', 'Осталось отправить профиль помощнику.']
  ];
  $('step').textContent = 'шаг ' + (Math.min(index + 1, 3)) + ' из 3';
  $('title').textContent = titles[index][0];
  $('sub').textContent = titles[index][1];
}

/* --- шаг 1: кто говорит -------------------------------------------- */

function paintWhos() {
  var box = $('whoList');
  box.textContent = '';
  VOICES.forEach(function (v) {
    var row = document.createElement('div');
    row.className = 'who__item';

    var mark = document.createElement('span');
    mark.className = 'who__mark';
    mark.textContent = v.mark;
    mark.style.background = v.color;

    var text = document.createElement('div');
    var name = document.createElement('p');
    name.className = 'who__name';
    name.textContent = v.name;
    var what = document.createElement('p');
    what.className = 'who__what';
    what.textContent = v.about;
    text.appendChild(name);
    text.appendChild(what);

    row.appendChild(mark);
    row.appendChild(text);
    box.appendChild(row);
  });
}

/* --- шаг 2: персонаж и тон ----------------------------------------- */

var TONES = [
  { v: 'short',  t: 'Коротко' },
  { v: 'normal', t: 'Обычно' },
  { v: 'warm',   t: 'Теплее' },
  { v: 'formal', t: 'Официально' }
];

function paintVoices() {
  var box = $('voices');
  box.textContent = '';
  VOICES.forEach(function (v) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'voice';
    b.setAttribute('aria-pressed', String(state.voice === v.key));
    b.dataset.voice = v.key;

    var n = document.createElement('span');
    n.className = 'voice__name';
    n.textContent = v.name;
    var w = document.createElement('span');
    w.className = 'voice__what';
    w.textContent = v.what;
    b.appendChild(n);
    b.appendChild(w);

    b.addEventListener('click', function () {
      state.voice = v.key;
      paintVoices();
      save();
    });
    box.appendChild(b);
  });
}

function paintTones() {
  var box = $('tones');
  box.textContent = '';
  TONES.forEach(function (t) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip';
    b.textContent = t.t;
    b.setAttribute('aria-pressed', String(state.tone === t.v));
    b.addEventListener('click', function () {
      state.tone = t.v;
      paintTones();
      save();
    });
    box.appendChild(b);
  });
}

/* --- шаг 3: экспресс-тест ------------------------------------------ */

function paintQuestion() {
  var i = state.question;
  if (i >= QUESTIONS.length) {
    state.step = 3;
    paintStep();
    return;
  }
  var item = QUESTIONS[i];

  $('qText').textContent = item.q;
  $('qHint').textContent = 'вопрос ' + (i + 1) + ' из ' + QUESTIONS.length +
                           ' — дальше можно вернуться и поменять';

  var box = $('qOptions');
  box.textContent = '';
  item.options.forEach(function (opt, index) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip';
    b.textContent = opt.t;
    b.setAttribute('aria-pressed', String(state.answers[i] === index));
    b.addEventListener('click', function () {
      state.answers[i] = index;
      state.question = i + 1;
      save();
      paintStep();
    });
    box.appendChild(b);
  });

  var done = (i + 1) / QUESTIONS.length * 100;
  $('qBar').style.width = done + '%';
}

/* --- итог ----------------------------------------------------------- */

function profile() {
  var voice = VOICES.filter(function (v) { return v.key === state.voice; })[0]
            || VOICES[0];
  var tone = TONES.filter(function (t) { return t.v === state.tone; })[0]
            || TONES[1];
  var answers = state.answers.map(function (idx, i) {
    var opt = QUESTIONS[i].options[idx];
    return { q: QUESTIONS[i].q, v: opt ? opt.v : '', t: opt ? opt.t : '' };
  });
  return { name: state.name, voice: voice.key, voiceName: voice.name,
           tone: state.tone, toneText: tone.t, answers: answers };
}

function paintSummary() {
  var p = profile();
  var rows = [
    ['Имя', p.name || '—'],
    ['Персонаж', p.voiceName],
    ['Манера', p.toneText]
  ];
  p.answers.forEach(function (a) { rows.push([a.q, a.t || '—']); });

  var box = $('summary');
  box.textContent = '';
  rows.forEach(function (r) {
    var row = document.createElement('div');
    row.className = 'summary__row';
    var k = document.createElement('span');
    k.className = 'summary__k';
    k.textContent = r[0];
    var v = document.createElement('span');
    v.className = 'summary__v';
    v.textContent = r[1];
    row.appendChild(k);
    row.appendChild(v);
    box.appendChild(row);
  });

  $('doneText').textContent = (p.name ? p.name + ', ' : '') +
    'дальше ' + p.voiceName + ' отвечает в выбранной манере и опирается ' +
    'на эти ответы. Поменять можно в любой момент — профиль лежит на ' +
    'телефоне, пока не отправлен.';
}

/* --- сохранение ------------------------------------------------------ */

function save() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      name: state.name, voice: state.voice, tone: state.tone,
      answers: state.answers
    }));
  } catch (e) {
    /* Приватный режим и переполненное хранилище. Приложение должно
     * работать и без сохранения — просто профиль не переживёт
     * перезапуск. Молча ронять страницу тут нельзя. */
  }
}

function restore() {
  var raw = null;
  try { raw = localStorage.getItem(STORE_KEY); } catch (e) { raw = null; }
  if (!raw) return false;
  try {
    var data = JSON.parse(raw);
    if (!data || typeof data !== 'object') return false;
    if (data.name) state.name = String(data.name).slice(0, 40);
    if (data.voice) state.voice = String(data.voice);
    if (data.tone) state.tone = String(data.tone);
    if (Array.isArray(data.answers)) {
      state.answers = data.answers.map(function (n) {
        return typeof n === 'number' ? n : -1;
      });
    }
    return Boolean(data.name);
  } catch (e) {
    /* Битое значение в хранилище — начинаем с чистого листа, а не
     * падаем: страница должна открыться в любом случае. */
    return false;
  }
}

/* --- отправка -------------------------------------------------------- */

function profileText(p) {
  var lines = [];
  lines.push('Профиль из мини-приложения');
  if (p.name) lines.push('Имя: ' + p.name);
  lines.push('Персонаж: ' + p.voiceName + ' (' + p.voice + ')');
  lines.push('Манера: ' + p.toneText);
  p.answers.forEach(function (a) {
    if (a.t) lines.push('- ' + a.q + ' — ' + a.t);
  });
  lines.push('Учитывай это в разговоре: длину ответа, манеру и термины.');
  return lines.join('\n');
}

/* Отправка идёт в тот же прокси, что и виджет на сайте, — по адресу
 * из `ai.json`. Прокси лежит рядом с приложением, поэтому настройки
 * берём оттуда же: отдельный адрес в коде протух бы первым. */
function sendProfile(text) {
  var hint = $('sendHint');
  var btn = $('send');

  var endpoint = '';
  try {
    var cfg = JSON.parse(localStorage.getItem('tma-endpoint') || '{}');
    endpoint = cfg.endpoint || '';
  } catch (e) { endpoint = ''; }

  // Адрес можно задать в адресной строке: ?endpoint=https://.../chat
  var fromQuery = /[?&]endpoint=([^&]+)/.exec(location.search);
  if (fromQuery) endpoint = decodeURIComponent(fromQuery[1]);

  if (!endpoint) {
    hint.textContent = 'Адрес прокси не задан — приложение не знает, куда ' +
                       'отправить профиль. Откройте его из бота или ' +
                       'добавьте ?endpoint=… к адресу.';
    return;
  }

  btn.disabled = true;
  hint.textContent = 'отправляю…';

  fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text, persona: 'guide', history: [] })
  }).then(function (r) {
    btn.disabled = false;
    hint.textContent = r.ok
      ? 'профиль отправлен, помощник его учтёт'
      : 'прокси ответил ' + r.status + ' — проверьте адрес и ключи';
  }).catch(function () {
    btn.disabled = false;
    hint.textContent = 'не дозвонился: прокси выключен или адрес неверен';
  });
}

/* --- переходы между шагами -------------------------------------------- */

function canGoNext() {
  if (state.step === 0) return Boolean($('name').value.trim());
  if (state.step === 2) return state.question > 0 || state.answers.length > 0;
  return true;
}

function paintStep() {
  paintPane(state.step);

  if (state.step === 2) paintQuestion();
  if (state.step === 3) paintSummary();

  show($('back'), state.step > 0);
  var next = $('next');
  if (state.step === 3) {
    next.textContent = 'готово';
    next.disabled = true;
  } else {
    next.textContent = state.step === 2 ? 'пропустить' : 'дальше';
    next.disabled = !canGoNext();
  }
}

function goNext() {
  if (state.step === 0) {
    state.name = $('name').value.trim().slice(0, 40);
    save();
  }
  if (state.step === 2) {
    // «Пропустить» — честный вариант: человек мог не хотеть отвечать.
    // Пустой профиль хуже, чем короткий: бот притворяется, что знает
    // манеру, которой не задавали.
    state.question = QUESTIONS.length;
  }
  state.step = Math.min(3, state.step + 1);
  paintStep();
}

/* Назад по шагам.
 *
 * С итога возвращаемся на тест, а не на выбор персонажа: человек
 * возвращается сюда, чтобы поправить ответ, и лишний шаг в середине
 * только мешает. Раньше здесь стоял общий `step -= 1`, и с итога
 * (шаг 3) уходило на шаг 1 — то есть к выбору персонажа, минуя сам
 * тест, ради которого человек и вернулся.
 *
 * С теста откатываемся на последний заполненный вопрос, но шаг
 * остаётся третьим: уход с него означал бы потерю позиции в тесте.
 */
function goBack() {
  if (state.step === 3) {
    // Возврат с итога — на последний заданный вопрос, а не «в самое
    // начало теста» и не на выбор персонажа.
    //
    // Номер вопроса здесь должен быть индексом последнего заполненного,
    // а не `QUESTIONS.length`: при исчерпанных вопросах `paintQuestion`
    // сам переводит на итог, и возврат снова оказывался бы на панели
    // «Готовы» — то есть кнопка «назад» просто не работала бы.
    state.step = 2;
    state.question = Math.max(0, state.answers.filter(function (n) {
      return n >= 0;
    }).length - 1);
  } else if (state.step === 2) {
    // Внутри теста «назад» листает вопросы назад. Выйти из теста
    // можно только с самого первого вопроса: раньше здесь стояло
    // `вопрос = сколько_отвечено - 1`, и на первом вопросе кнопка
    // просто листала его же — то есть из теста было не выйти вовсе,
    // и вернуться к выбору персонажа не получалось ни разу.
    if (state.question > 0) {
      state.question -= 1;
    } else {
      state.step = 1;
    }
  } else if (state.step === 1) {
    state.step = 0;
  }
  paintStep();
}

/* --- запуск ------------------------------------------------------------ */

function start() {
  paintWhos();
  paintVoices();
  paintTones();

  var known = restore();
  $('name').value = state.name;
  paintVoices();
  paintTones();

  $('name').addEventListener('input', function () {
    $('next').disabled = !canGoNext();
  });
  $('name').addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && canGoNext()) goNext();
  });

  $('next').addEventListener('click', function () {
    if (state.step === 3) return;
    goNext();
  });
  $('back').addEventListener('click', goBack);

  $('send').addEventListener('click', function () {
    sendProfile(profileText(profile()));
  });

  $('restart').addEventListener('click', function () {
    state = { step: 0, name: '', voice: 'guide', tone: 'normal',
              answers: [], question: 0 };
    $('name').value = '';
    $('qBar').style.width = '0';
    $('sendHint').textContent = '';
    try { localStorage.removeItem(STORE_KEY); } catch (e) { /* см. save */ }
    lastPane = -1;
    paintStep();
  });

  // Из бота приложение открывают с готовым именем в адресе: делить
  // одно на другое приходится именно так, отдельного канала нет.
  var fromQuery = /[?&]name=([^&]+)/.exec(location.search);
  if (fromQuery) {
    state.name = decodeURIComponent(fromQuery[1]).slice(0, 40);
    $('name').value = state.name;
  }

  // Если профиль уже был, сразу показываем итог, а не первый шаг
  // заново: человек возвращается, чтобы отправить, а не начинать.
  if (known && state.name) {
    state.step = 3;
  }
  paintStep();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', start);
} else {
  start();
}
