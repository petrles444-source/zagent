/* Виджет ИИ-агента — общий для всех страниц.
 *
 * Виджет ничего не знает про ключи и про модели: он спрашивает прокси, а
 * прокси уже на машине владельца. Адрес прокси и голос лежат в `ai.json`
 * рядом со страницей, поэтому туннель можно перезапустить и поменять
 * одну строку, не трогая этот файл.
 *
 * Ответ модели вставляется через textContent и собирается из узлов
 * DOM — то же рассуждение, что и в chat.js на главном сайте: текст из
 * сети нельзя отдавать разметкой, иначе это готовая дыра для <script>.
 */
'use strict';

const AI_MAX_HISTORY = 10;
const AI_MAX_CHARS = 1500;

/**
 * Адрес настроек выводится из адреса самого скрипта, а не пишется рядом
 * с ним строкой.
 *
 * Раньше виджет искал `ai.json` относительно страницы, и это работало,
 * пока копия скрипта лежала в каждой папке рядом со своей страницей.
 * Теперь скрипт один и общий для всех сайтов, а страницы живут в
 * разных папках — и жёстко записанный `ai.json` из `shared/` указал бы
 * не туда. Поэтому адрес берётся у самого скрипта и меняется имя файла.
 *
 * Адрес запоминается сразу при загрузке: `document.currentScript`
 * действителен только во время выполнения, а настройки читаются позже,
 * по `DOMContentLoaded`, и к тому моменту он уже пуст.
 */
const AI_CONFIG_URL = (function () {
  const here = document.currentScript && document.currentScript.src;
  if (!here) return 'ai.json';          // подстраховка: скрипт без адреса
  return here.replace(/ai\.js(\?.*)?$/, 'ai.json$1');
})();

const aiState = {
  config: null,
  history: [],
  busy: false,
  dom: {},
};

/* ---------------------------------------------------------------- формат */

/**
 * Разобрать простейшую разметку ответа: **жирный**, `код`, переносы строк.
 *
 * Узлы строятся явно, поэтому из ответа получаются только <strong>,
 * <code> и <br> — никакой посторонней разметки выполниться не может.
 */
function aiFormat(target, text) {
  target.textContent = '';
  String(text).split('\n').forEach((line, index) => {
    if (index) target.appendChild(document.createElement('br'));
    // Разделители сохраняются: split с группой оставляет их на месте.
    const parts = line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    for (const part of parts) {
      if (!part) continue;
      if (part.length > 4 && part.startsWith('**') && part.endsWith('**')) {
        const strong = document.createElement('strong');
        strong.textContent = part.slice(2, -2);
        target.appendChild(strong);
      } else if (part.length > 2 && part.startsWith('`') && part.endsWith('`')) {
        const code = document.createElement('code');
        code.textContent = part.slice(1, -1);
        target.appendChild(code);
      } else {
        target.appendChild(document.createTextNode(part));
      }
    }
  });
}

/* ------------------------------------------------------------------ видна */

function aiAddRow(kind, text) {
  const row = document.createElement('div');
  row.className = 'ai-row ' + kind;
  if (kind === 'bot') aiFormat(row, text);
  else row.textContent = text;
  aiState.dom.log.appendChild(row);
  aiState.dom.log.scrollTop = aiState.dom.log.scrollHeight;
  return row;
}

/* --------------------------------------------------------------- приём */

/**
 * Отправить вопрос прокси и показать ответ.
 *
 * Ошибка сети, обрыв и ответ «помощник не отвечает» — это три разных
 * случая, и посетителю нужны три разных слова: он должен понимать,
 * чинит он что-то или ждать.
 */
async function aiAsk(message) {
  if (aiState.busy) return;
  const text = String(message || '').trim().slice(0, AI_MAX_CHARS);
  if (!text) return;

  aiState.busy = true;
  aiState.dom.send.disabled = true;
  aiState.dom.input.value = '';

  aiAddRow('user', text);
  const typing = document.createElement('div');
  typing.className = 'ai-typing';
  typing.append(aiTypingDot(), aiTypingDot(), aiTypingDot());
  aiState.dom.log.appendChild(typing);
  aiState.dom.log.scrollTop = aiState.dom.log.scrollHeight;

  try {
    const response = await fetch(aiState.config.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        persona: aiState.config.persona || '',
        history: aiState.history.slice(-AI_MAX_HISTORY),
      }),
    });

    let payload = {};
    try {
      payload = await response.json();
    } catch {
      throw new Error('неразборный ответ');
    }

    typing.remove();

    if (!response.ok || !payload.ok) {
      const why = response.status === 429
        ? 'Слишком много вопросов подряд. Подождите минуту.'
        : (payload.error || 'Помощник сейчас не отвечает.');
      aiAddRow('sys', why);
      return;
    }

    const answer = String(payload.answer || '').trim();
    if (!answer) {
      aiAddRow('sys', 'Модель вернула пустой ответ.');
      return;
    }
    aiAddRow('bot', answer);
    // История пополняется только удавшимся обменом: неудачный запрос
    // не должен оставлять в контексте вопрос без ответа.
    aiState.history.push({ role: 'user', text });
    aiState.history.push({ role: 'assistant', text: answer });
    if (aiState.history.length > AI_MAX_HISTORY * 2) {
      aiState.history = aiState.history.slice(-AI_MAX_HISTORY * 2);
    }
  } catch {
    typing.remove();
    aiAddRow('sys', 'Связь с помощником прервалась.');
  } finally {
    aiState.busy = false;
    aiState.dom.send.disabled = false;
    aiState.dom.input.focus();
  }
}

function aiTypingDot() {
  const dot = document.createElement('i');
  return dot;
}

/* ------------------------------------------------------------------ сборка */

function aiBuild() {
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'ai-toggle';
  toggle.setAttribute('aria-expanded', 'false');
  const dot = document.createElement('span');
  dot.className = 'ai-dot';
  toggle.append(dot, document.createTextNode('спросить агента'));

  const panel = document.createElement('section');
  panel.className = 'ai-panel';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Помощник');

  const head = document.createElement('div');
  head.className = 'ai-head';
  const name = document.createElement('span');
  name.className = 'ai-name';
  const role = document.createElement('span');
  role.className = 'ai-role';
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'ai-close';
  close.textContent = '×';
  close.setAttribute('aria-label', 'Закрыть');
  head.append(name, role, close);

  const log = document.createElement('div');
  log.className = 'ai-log';
  log.setAttribute('role', 'log');
  log.setAttribute('aria-live', 'polite');

  const form = document.createElement('form');
  form.className = 'ai-form';
  const input = document.createElement('textarea');
  input.rows = 1;
  input.placeholder = 'спросить…';
  input.setAttribute('aria-label', 'Вопрос помощнику');
  const send = document.createElement('button');
  send.type = 'submit';
  send.textContent = '→';
  send.setAttribute('aria-label', 'Отправить');
  form.append(input, send);

  panel.append(head, log, form);
  document.body.append(toggle, panel);

  aiState.dom = { toggle, panel, name, role, close, log, form, input, send };

  toggle.addEventListener('click', () => aiOpen(!panel.hidden ? false : true));
  close.addEventListener('click', () => aiOpen(false));
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    aiAsk(input.value);
  });

  /* Enter отправляет, Shift+Enter переносит строку. В поле из одной строки
   * без этого нельзя было бы задать вопрос с переносом. */
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      aiAsk(input.value);
    }
  });

  /* Поле подстраивается под содержимое, но не выше шести строк. */
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });

  /* Esc закрывает панель: привычное поведение, и кнопка возвращает
   * фокус, чтобы страницу можно было дальше читать с клавиатуры. */
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !panel.hidden) aiOpen(false);
  });

  return toggle;
}

function aiOpen(open) {
  const { toggle, panel, input } = aiState.dom;
  panel.hidden = !open;
  toggle.setAttribute('aria-expanded', String(open));
  if (open) input.focus();
  else toggle.focus();
}

/* ------------------------------------------------------------------ старт */

/**
 * Поставить виджет на страницу.
 *
 * Настройки лежат в `ai.json`, а не в разметке: страниц много, а файл
 * один и тот же, и править его удобнее в одном месте, чем семь раз
 * в html.
 */
async function aiMount(options) {
  let config = {};
  try {
    const response = await fetch(AI_CONFIG_URL, { cache: 'no-store' });
    config = await response.json();
  } catch {
    config = {};
  }

  config = { ...(options || {}), ...config };
  const toggle = aiBuild();
  aiState.config = config;

  if (!config.endpoint) {
    // Адреса нет — виджет молчит, а не показывает форму, которая
    // заведомо ничего не отправит.
    toggle.hidden = true;
    return;
  }

  aiState.dom.name.textContent = config.agent || 'Помощник';
  aiState.dom.role.textContent = config.role || '';
  aiAddRow('sys', config.greeting || 'Спросите что-нибудь.');
}

document.addEventListener('DOMContentLoaded', () => {
  /* Каждая страница объявляет своё: голос и подпись. Подсказка с
   * приветствием живёт в ai.json, чтобы не дублировать её в разметке. */
  const meta = document.querySelector('meta[name="zagent-ai"]');
  let options = {};
  if (meta) {
    try {
      options = JSON.parse(meta.getAttribute('content') || '{}');
    } catch {
      options = {};
    }
  }
  aiMount(options);
});