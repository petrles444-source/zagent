/* Neural Archive — поведение портала.
 *
 * Всё, что показывается на экране, берётся из двух источников: файл
 * `assets/catalog.json` (описания работ) и события плеера. Никаких
 * выдуманных чисел: если Ruffle не сообщил метаданные, в строке
 * состояния будет прочерк, а не «60 FPS».
 *
 * Два отличия от образца, из которого взят дизайн:
 *
 * 1. Нет регулятора скорости. В этой сборке Ruffle не даёт управлять
 *    темпом — метода setSpeed/setPlaybackRate у элемента ruffle-player
 *    нет. Кнопки «0.5×…2×» в образце были украшением; здесь их нет,
 *    чтобы не обещать то, что не работает.
 * 2. Полоса прогресса идёт по времени стены, а не по кадрам: события «показан
 *    кадр» у Ruffle тоже нет. Длительность берётся из метаданных
 *    (numFrames / frameRate), поэтому для однопроходных работ полоса
 *    близка к точной.
 */
'use strict';

const CATALOG_URL = 'assets/catalog.json';
const FAV_KEY = 'neural-archive:favorites';

const SPEED_KEYS = new Set(['1', '2', '3']);

/** Короткое уведомление в правом нижнем углу. */
function toast(text, kind = 'ok', ms = 3200) {
  const box = document.getElementById('toasts');
  const node = document.createElement('div');
  node.className = 'toast ' + kind;
  node.textContent = text;
  box.appendChild(node);
  setTimeout(() => node.remove(), ms);
}

/** Подсветка статуса движка в шапке. */
function setEngine(state, text) {
  const box = document.getElementById('engineStatus');
  const label = document.getElementById('engineText');
  box.classList.remove('ok', 'bad', 'busy');
  if (state) box.classList.add(state);
  label.textContent = text;
}

/* ---------------------------------------------------------- каталог */

let catalog = [];
let player = null;      // текущий экземпляр ruffle-player
let current = null;     // текущая работа
let startedAt = 0;      // когда началось воспроизведение
let playing = false;
let loadedMeta = null;  // метаданные от плеера

function readFavorites() {
  try {
    return JSON.parse(localStorage.getItem(FAV_KEY) || '[]');
  } catch {
    return [];
  }
}

function isFavorite(id) {
  return readFavorites().includes(id);
}

function toggleFavorite(id) {
  const list = readFavorites();
  const at = list.indexOf(id);
  if (at >= 0) list.splice(at, 1);
  else list.push(id);
  localStorage.setItem(FAV_KEY, JSON.stringify(list));
  renderCatalog();
}

/**
 * Найти описание работы по адресу файла.
 * Адреса сравниваются без учёта слеша: файл мог прийти по URL, и тогда
 * путь начинается с чужого домена — но это всё та же работа.
 */
function findBySrc(src) {
  const tail = String(src || '').split('/').pop();
  return catalog.find((item) => item.url.split('/').pop() === tail) || null;
}

function visibleCatalog() {
  const chip = document.querySelector('.chip[aria-pressed="true"][data-cat]');
  const cat = chip ? chip.dataset.cat : 'all';
  let items = catalog.slice();
  if (cat === 'fav') items = items.filter((item) => isFavorite(item.id));
  else if (cat !== 'all') items = items.filter((item) => item.cat.includes(cat));
  // По умолчанию год по возрастанию — «ранние работы сверху», как в
  // каталоге музея. Кнопка переворачивает порядок.
  items.sort((a, b) => (sortedDesc ? b.year - a.year : a.year - b.year));
  return items;
}

let sortedDesc = false;

function renderCatalog() {
  const grid = document.getElementById('grid');
  const empty = document.getElementById('empty');
  const items = visibleCatalog();
  grid.innerHTML = '';
  empty.hidden = items.length > 0;
  for (const item of items) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'card';
    if (current && current.id === item.id) card.classList.add('playing');

    const thumb = document.createElement('div');
    thumb.className = 'thumb';
    thumb.textContent = (item.title || '?').trim().charAt(0).toUpperCase();

    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = item.title;

    const meta = document.createElement('div');
    meta.className = 'meta';
    const year = document.createElement('span');
    year.textContent = item.year;
    const kind = document.createElement('span');
    kind.textContent = item.cat[0];
    const fav = document.createElement('span');
    fav.className = 'fav';
    fav.textContent = isFavorite(item.id) ? '♥' : '♡';
    fav.setAttribute('role', 'button');
    fav.setAttribute('aria-pressed', String(isFavorite(item.id)));
    fav.tabIndex = 0;
    fav.title = 'В избранное';
    meta.append(year, kind, fav);

    card.append(thumb, title, meta);
    card.addEventListener('click', (event) => {
      // Сердечко внутри карточки: клик по нему не должен запускать файл.
      if (event.target === fav) {
        toggleFavorite(item.id);
        return;
      }
      loadUrl(item.url, item.title);
    });
    grid.appendChild(card);
  }
  document.getElementById('statCount').textContent = catalog.length;
}

/* ---------------------------------------------------------- плеер */

function setControlsEnabled(on) {
  for (const id of ['btnToggle', 'btnStop', 'btnFull', 'btnMute', 'btnDownload', 'btnShare']) {
    document.getElementById(id).disabled = !on;
  }
  document.getElementById('btnToggle').textContent = playing ? '❚❚ Пауза' : '▶ Пуск';
}

/**
 * Готов ли движок.
 *
 * Проверять `customElements.get('ruffle-player')` бесполезно: в этой
 * сборке Ruffle регистрирует элемент лениво, при первом создании
 * игрока. Признак готовности — появление `RufflePlayer.sources.local`
 * с функцией createPlayer. Именно её и надо звать, чтобы получить
 * настоящий элемент: `createElement('ruffle-player')` создал бы
 * безымянный тег, который ничего не играет.
 */
function engineReady() {
  // Элемент ruffle-player в этой сборке регистрируется лениво, при
  // первом createPlayer(), поэтому признак готовности — не он, а
  // появление загрузчика с функцией создания игрока.
  const local = window.RufflePlayer && window.RufflePlayer.sources
    && window.RufflePlayer.sources.local;
  return !!(local && typeof local.createPlayer === 'function');
}

function engineVersion() {
  const local = window.RufflePlayer && window.RufflePlayer.sources
    && window.RufflePlayer.sources.local;
  return (local && local.version) || '';
}

/** Убрать прежний плеер и поставить новый в сцену. */
function makePlayer() {
  if (player) player.remove();
  document.getElementById('idle').hidden = true;
  if (!engineReady()) {
    setEngine('bad', 'движок не загрузился');
    toast('Ruffle не загрузился: проверьте папку ruffle/', 'err', 9000);
    return null;
  }
  player = window.RufflePlayer.sources.local.createPlayer();
  player.id = 'movie';
  player.style.width = '100%';
  player.style.height = '100%';
  document.getElementById('stage').appendChild(player);

  player.addEventListener('loadedmetadata', () => {
    // Событие приходит ПУСТЫМ: Ruffle отдаёт метаданные свойством
    // элемента, а в CustomEvent.detail их нет. Читать event.detail —
    // верный на вид способ не показать ничего.
    loadedMeta = player.metadata || null;
    document.getElementById('hudEngine').textContent =
      'ruffle ' + engineVersion() + (loadedMeta ? ' · ' + loadedMeta.frameRate + ' fps' : '');
    paintHud();
  });
  player.addEventListener('loadeddata', () => {
    setEngine('ok', 'движок готов');
    playing = true;
    startedAt = Date.now();
    setControlsEnabled(true);
    renderCatalog();
  });
  return player;
}

function paintHud() {
  const meta = loadedMeta || {};
  document.getElementById('hudName').textContent = current ? current.title : '—';
  document.getElementById('hudFps').textContent =
    meta.numFrames ? meta.numFrames + ' кадров' : '— кадров';
  document.getElementById('hudTime').textContent = formatTime(secondsPlayed());
  const total = meta.numFrames && meta.frameRate
    ? meta.numFrames / meta.frameRate : 0;
  const bar = document.getElementById('progress');
  bar.style.right = total > 0
    ? (100 - Math.min(100, (secondsPlayed() / total) * 100)) + '%'
    : '100%';
}

function secondsPlayed() {
  return playing && current ? (Date.now() - startedAt) / 1000 : 0;
}

function formatTime(sec) {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  return String(m).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
}

/** Загрузить работу по адресу. */
function loadUrl(url, title) {
  if (!url) return;
  try {
    new URL(url, location.href);
  } catch {
    toast('Не похоже на адрес: ' + url, 'err');
    return;
  }
  current = findBySrc(url) || { id: 'url:' + url, title: title || 'Загруженный файл', cat: ['interactive'], year: new Date().getFullYear() };
  setEngine('busy', 'загрузка');
  document.getElementById('hudEngine').textContent = 'загрузка…';
  playing = false;
  loadedMeta = null;
  const created = makePlayer();
  if (!created) return;
  created.load({ url: current.url });
  setControlsEnabled(true);
  paintHud();
  renderCatalog();
}

/** Загрузить файл, выбранный или перетащенный. Объект живёт в памяти. */
function loadFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.swf')) {
    toast('Нужен файл .swf, а не ' + file.name, 'err');
    return;
  }
  current = { id: 'file:' + file.name, title: file.name, cat: ['interactive'], year: new Date().getFullYear(), url: '' };
  setEngine('busy', 'чтение файла');
  const reader = new FileReader();
  reader.onload = () => {
    makePlayer().load({ data: new Uint8Array(reader.result), swfFileName: file.name });
    setControlsEnabled(true);
    paintHud();
    renderCatalog();
  };
  reader.onerror = () => {
    setEngine('bad', 'файл не прочитан');
    toast('Не удалось прочитать файл', 'err');
  };
  reader.readAsArrayBuffer(file);
}

function togglePlay() {
  if (!player) return;
  if (playing) {
    player.pause();
    playing = false;
  } else {
    player.play();
    playing = true;
    startedAt = Date.now();
  }
  setControlsEnabled(true);
  paintHud();
}

function stopAll() {
  if (player) player.remove();
  player = null;
  current = null;
  playing = false;
  loadedMeta = null;
  document.getElementById('idle').hidden = false;
  document.getElementById('hudName').textContent = '—';
  document.getElementById('hudTime').textContent = '00:00';
  document.getElementById('hudFps').textContent = '— кадров';
  document.getElementById('hudEngine').textContent = 'idle';
  document.getElementById('progress').style.right = '100%';
  setControlsEnabled(false);
  renderCatalog();
}

async function downloadCurrent() {
  if (!current || !current.url) {
    toast('Скачивать нечего: файл был открыт с вашего диска', 'warn');
    return;
  }
  try {
    const response = await fetch(current.url);
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const blob = await response.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href;
    a.download = current.url.split('/').pop();
    a.click();
    URL.revokeObjectURL(href);
    toast('Скачивание начато', 'ok');
  } catch (error) {
    toast('Не скачалось: ' + error.message, 'err');
  }
}

async function shareCurrent() {
  if (!current || !current.url) {
    toast('Поделиться можно только работой из каталога', 'warn');
    return;
  }
  const url = new URL(current.url, location.href).href;
  if (navigator.share) {
    try {
      await navigator.share({ title: current.title, url });
      return;
    } catch { /* пользователь закрыл — молча, это не ошибка */ }
  }
  try {
    await navigator.clipboard.writeText(url);
    toast('Ссылка скопирована', 'ok');
  } catch {
    toast('Скопируйте вручную: ' + url, 'warn');
  }
}

/* ---------------------------------------------------------- фон */

function startBackground() {
  const canvas = document.getElementById('bg');
  const ctx = canvas.getContext('2d');
  const dots = [];
  const resize = () => {
    canvas.width = canvas.clientWidth;
    canvas.height = canvas.clientHeight;
  };
  resize();
  addEventListener('resize', resize);

  for (let i = 0; i < 46; i++) {
    dots.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 1.7 + 0.4,
      vx: (Math.random() - 0.5) * 0.22,
      vy: (Math.random() - 0.5) * 0.22,
      hue: Math.random() < 0.5 ? '0,240,255' : '252,227,0',
    });
  }

  // Линии между близкими точками — «сеть». Нагрузка на кадр держится
  // ниже 1%: расстояния считаются квадратом, корень не берётся.
  function frame() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const dot of dots) {
      dot.x += dot.vx;
      dot.y += dot.vy;
      if (dot.x < 0 || dot.x > canvas.width) dot.vx *= -1;
      if (dot.y < 0 || dot.y > canvas.height) dot.vy *= -1;
    }
    for (let i = 0; i < dots.length; i++) {
      for (let j = i + 1; j < dots.length; j++) {
        const dx = dots[i].x - dots[j].x;
        const dy = dots[i].y - dots[j].y;
        const d2 = dx * dx + dy * dy;
        if (d2 < 15000) {
          ctx.strokeStyle = 'rgba(0,240,255,' + (1 - d2 / 15000) * 0.13 + ')';
          ctx.beginPath();
          ctx.moveTo(dots[i].x, dots[i].y);
          ctx.lineTo(dots[j].x, dots[j].y);
          ctx.stroke();
        }
      }
    }
    for (const dot of dots) {
      ctx.fillStyle = 'rgba(' + dot.hue + ',0.5)';
      ctx.beginPath();
      ctx.arc(dot.x, dot.y, dot.r, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

/* ---------------------------------------------------------- запуск */

function wire() {
  const fileInput = document.getElementById('fileInput');
  document.getElementById('btnPick').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    loadFile(fileInput.files[0]);
    fileInput.value = '';
  });

  document.getElementById('btnUrl').addEventListener('click', () => {
    const value = document.getElementById('urlInput').value.trim();
    if (!value) {
      toast('Укажите адрес файла', 'warn');
      return;
    }
    loadUrl(value);
  });
  document.getElementById('urlInput').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') document.getElementById('btnUrl').click();
  });

  document.getElementById('btnDemo').addEventListener('click', () => {
    const demo = catalog.find((item) => item.cat.includes('generated'));
    if (demo) loadUrl(demo.url, demo.title);
  });

  document.getElementById('btnToggle').addEventListener('click', togglePlay);
  document.getElementById('btnStop').addEventListener('click', stopAll);
  document.getElementById('btnDownload').addEventListener('click', downloadCurrent);
  document.getElementById('btnShare').addEventListener('click', shareCurrent);
  document.getElementById('btnMute').addEventListener('click', (event) => {
    if (!player) return;
    const muted = player.volume === 0;
    player.volume = muted ? 1 : 0;
    event.currentTarget.textContent = muted ? '♪' : '🔇';
  });
  document.getElementById('btnFull').addEventListener('click', () => {
    if (player) player.requestFullscreen();
  });

  document.getElementById('btnSort').addEventListener('click', (event) => {
    sortedDesc = !sortedDesc;
    event.currentTarget.textContent = sortedDesc ? 'Год ↓' : 'Год ↑';
    renderCatalog();
  });

  for (const chip of document.querySelectorAll('.chip[data-cat]')) {
    chip.addEventListener('click', () => {
      for (const other of document.querySelectorAll('.chip[data-cat]')) {
        other.setAttribute('aria-pressed', String(other === chip));
      }
      renderCatalog();
    });
  }

  // Перетаскивание файла в любое место окна.
  const drop = document.getElementById('drop');
  for (const type of ['dragenter', 'dragover']) {
    document.addEventListener(type, (event) => {
      event.preventDefault();
      drop.classList.add('hot');
    });
  }
  for (const type of ['dragleave', 'drop']) {
    document.addEventListener(type, (event) => {
      event.preventDefault();
      if (type === 'dragleave' && event.target !== document.documentElement) return;
      drop.classList.remove('hot');
    });
  }
  document.addEventListener('drop', (event) => {
    const file = event.dataTransfer && event.dataTransfer.files[0];
    if (file) loadFile(file);
  });

  // Горячие клавиши. Цифры и пробел ловим только когда фокус не в поле
  // ввода: иначе человек не мог бы набрать адрес.
  document.addEventListener('keydown', (event) => {
    const typing = /^(INPUT|TEXTAREA)$/.test(event.target.tagName);
    if (event.key === 'Escape') {
      stopAll();
      return;
    }
    if (typing || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.code === 'Space') {
      event.preventDefault();
      togglePlay();
    } else if (SPEED_KEYS.has(event.key)) {
      // Номера 1..3 переключают скорость; регулятора скорости у Ruffle
      // нет, поэтому номера переключают работы каталога.
      const index = Number(event.key) - 1;
      if (catalog[index]) loadUrl(catalog[index].url, catalog[index].title);
    } else if (event.key === 'o' || event.key === 'O' || event.key === 'щ') {
      fileInput.click();
    }
  });
}

async function boot() {
  startBackground();
  wire();
  setControlsEnabled(false);
  try {
    const response = await fetch(CATALOG_URL);
    catalog = await response.json();
  } catch {
    toast('Каталог не загрузился: ' + CATALOG_URL, 'err');
    catalog = [];
  }
  renderCatalog();
  document.getElementById('demoList').textContent = catalog.length
    ? 'в каталоге: ' + catalog.length + ' работ — все воспроизводятся'
    : '';
  document.getElementById('statTotal').textContent = catalog.reduce(
    (sum, item) => sum + (item.frames || 0), 0);

  // Движок: элемент ruffle-player появляется, когда загрузчик выполнил
  // регистрацию. Пока его нет — статус «загрузка», и через секунду
  // повторная проверка: ядро весит десятки мегабайт.
  let tries = 0;
  const waitEngine = setInterval(() => {
    tries++;
    if (customElements.get('ruffle-player')) {
      clearInterval(waitEngine);
      setEngine('ok', 'ruffle на месте');
      // В подвале теперь ссылка «обновить страницу» с меткой сборки:
      // её проставляет tools/build_site.py, и текст здесь её бы стёр.
    } else if (tries > 60) {
      clearInterval(waitEngine);
      setEngine('bad', 'движок не загрузился');
      toast('Ruffle не загрузился: проверьте папку ruffle/', 'err', 9000);
    }
  }, 250);

  // Строка состояния обновляется раз в полсекунды: время и полоса идут
  // по часам стены, без событий от плеера их не обновить.
  setInterval(() => {
    if (player && playing) paintHud();
  }, 500);
}

document.addEventListener('DOMContentLoaded', boot);
