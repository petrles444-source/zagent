/* Neural Archive — виджет помощника.
 *
 * Виджет ничего не знает про ключи и вообще про модели: он спрашивает
 * прокси, а прокси уже на твоём компьютере. Адрес прокси лежит в
 * `assets/config.json`, поэтому туннель можно перезапустить (и он
 * выдаст новый адрес) без правки этого файла — достаточно поменять
 * одну строку в конфиге.
 *
 * Текст ответа модели вставляется через textContent, а не через
 * innerHTML: модель может вернуть что угодно, включая готовый <script>,
 * и вставлять это через разметку — дыра, которой пользуются все, кто
 * так делает.
 */
'use strict';

const CONFIG_URL = 'assets/config.json';
const MAX_LOCAL_HISTORY = 12;

let botConfig = { endpoint: '', greeting: '' };
let botBusy = false;
let botHistory = [];
const botLog = [];

function botToast(text) {
  const host = document.querySelector('.chat-log');
  const row = document.createElement('div');
  row.className = 'chat-row sys';
  row.textContent = text;
  host.appendChild(row);
  host.scrollTop = host.scrollHeight;
}

/**
 * Разобрать простейшую разметку ответа: **жирный**, `код` и переносы строк.
 *
 * Через DOM, а не через innerHTML: модель возвращает текст, а текст из
 * сети нельзя вставлять разметкой. Узлы строятся явно — из ответа
 * получаются только <strong>, <code> и <br>, так что никакой <script>
 * выполниться не может.
 */
function botFormat(target, text) {
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

/** Строка в логе: кто говорит и что. */
function botSay(who, text) {
  const host = document.querySelector('.chat-log');
  const row = document.createElement('div');
  row.className = 'chat-row ' + (who === 'user' ? 'me' : who === 'bot' ? 'bot' : 'sys');
  const who2 = document.createElement('b');
  who2.textContent = who === 'user' ? 'вы' : who === 'bot' ? 'помощник' : 'система';
  const body = document.createElement('p');
  botFormat(body, text);
  row.append(who2, body);
  host.appendChild(row);
  host.scrollTop = host.scrollHeight;
  return row;
}

/** Показать «думает» отдельной строкой, чтобы её потом заменить. */
function botPending() {
  const row = botSay('sys', 'думаю…');
  row.classList.remove('sys');
  row.classList.add('bot', 'waiting');
  return row;
}

async function botAsk(question) {
  if (botBusy || !question.trim()) return;
  if (!botConfig.endpoint) {
    botSay('sys', 'помощник не настроен: нет адреса прокси в config.json');
    return;
  }
  botBusy = true;
  document.querySelector('.chat-send').disabled = true;
  botSay('user', question);
  botHistory.push({ role: 'user', text: question });
  if (botHistory.length > MAX_LOCAL_HISTORY) botHistory.shift();

  const pending = botPending();
  try {
    const response = await fetch(botConfig.endpoint.replace(/\/$/, '') + '/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: question, history: botHistory.slice(0, -1) }),
    });
    const data = await response.json().catch(() => ({}));
    pending.remove();
    if (!response.ok || !data.ok) {
      botSay('sys', data.error || ('ошибка ' + response.status));
      return;
    }
    botSay('bot', data.answer);
    botHistory.push({ role: 'assistant', text: data.answer });
    if (botHistory.length > MAX_LOCAL_HISTORY) botHistory.shift();
    const meta = document.querySelector('.chat-meta');
    if (meta) {
      const seconds = data.duration_ms ? Math.round(data.duration_ms / 100) / 10 : null;
      meta.textContent = (data.model || 'модель') + (seconds ? ' · ' + seconds + ' с' : '');
    }
  } catch (error) {
    pending.remove();
    botSay('sys', 'связь с помощником прервалась: ' + error.message);
  } finally {
    botBusy = false;
    document.querySelector('.chat-send').disabled = false;
  }
}

function botWire() {
  const form = document.querySelector('.chat-form');
  const input = document.querySelector('.chat-input');
  // Быстрые вопросы: человеку не нужно придумывать формулировку, а
  // помощнику — гадать. Текст вопроса лежит в data-q, поэтому в разметке
  // его не видно дважды и он не расходится с подписью кнопки.
  for (const button of document.querySelectorAll('.chat-quick .chip')) {
    button.addEventListener('click', () => {
      input.value = button.dataset.q || '';
      input.focus();
      form.requestSubmit();
    });
  }
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const text = input.value;
    input.value = '';
    botAsk(text);
  });
  // Ctrl+Enter отправляет, обычный Enter переносит строку: в вопросах
  // про код перенос строки нужен чаще, чем отправка.
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
}

async function botBoot() {
  botWire();
  let config = {};
  try {
    const response = await fetch(CONFIG_URL, { cache: 'no-store' });
    config = await response.json();
  } catch {
    config = {};
  }
  botConfig = {
    endpoint: String(config.bot_endpoint || ''),
    greeting: String(config.bot_greeting || ''),
  };
  if (botConfig.greeting) botSay('bot', botConfig.greeting);
  botSay('sys', botConfig.endpoint
    ? 'спрашивайте про сайт: что за архив, как загрузить свою .swf, что такое Ruffle'
    : 'помощник пока не подключён');
}

document.addEventListener('DOMContentLoaded', botBoot);
