/* app.js — заглушка «Поток».
 *
 * Задача файла ровно одна: превратить поле ввода в частицы на
 * фотографии. Никаких библиотек и никаких загрузок — потому что
 * страница обязана открываться без интернета, а лишние 200 КБ
 * зависимостей ради сорока точек было бы абсурдом.
 *
 * Как устроено:
 *   — поле ввода добавляет по одному узлу на каждый символ;
 *   — узлы живут в прямоугольнике экрана и медленно дрейфуют;
 *   — линия рисуется между узлами, которые ближе порога;
 *   — счётчики показывают, сколько узлов и связей получилось.
 *
 * Отказоустойчивость (это заглушка, она обязана открываться везде):
 *   — нет canvas или нет 2d-контекста: скрипт молча ничего не рисует,
 *     но счётчики продолжают считать узлы, а страница остаётся
 *     читаемой;
 *   — prefers-reduced-motion: анимации нет, узлы рисуются один раз
 *     на событие, а не каждый кадр;
 *   — узлов не больше N: иначе длинный текст в поле уронит страницу
 *     сотнями линий.
 */
(function () {
  'use strict';

  /* Порог связи: дальше этого расстояния линия не рисуется.
   * Подобран на глаз по размеру экрана: при 150 пикселях сеть
   * выглядит сеткой, при 60 — кашей. */
  var LINK_DIST = 150;
  /* Больше 70 узлов поле не держит: со временем старые узлы
   * исчезают, поэтому это не «максимум текста», а предохранитель. */
  var MAX_NODES = 70;
  /* Скорость дрейфа в пикселях на кадр. Медленная намеренно:
   * движение должно читаться как дыхание, а не как ролик. */
  var DRIFT = 0.22;

  var canvas = document.getElementById('net');
  var input = document.getElementById('seed');
  var clearBtn = document.getElementById('clear');
  var pulseBtn = document.getElementById('pulse');
  var nodesOut = document.getElementById('nodes');
  var linksOut = document.getElementById('links');

  /* Если обязательных элементов нет — это не наша страница.
   * Выходим молча: пустая ошибка в консоли странице не нужна. */
  if (!input || !nodesOut || !linksOut) { return; }

  var ctx = canvas && canvas.getContext ? canvas.getContext('2d') : null;
  var reduced = false;
  try {
    reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch (e) {
    /* Старый движок без matchMedia: просто считаем, что
     * анимация разрешена. */
    reduced = false;
  }

  /* Узлы: только координаты и скорость. Больше хранить нечего,
   * поэтому массив вместо объектов с классами. */
  var nodes = [];

  /* Последние показанные значения счётчиков: DOM трогаем только
   * когда число реально изменилось, иначе экран перерисовывался
   * бы на каждый кадр. */
  var lastNodes = -1;
  var lastLinks = -1;

  function sizeCanvas() {
    /* devicePixelRatio учитываем, иначе на плотном экране сеть
     * расползалась бы и выглядела мыльной. */
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth || window.innerWidth;
    var h = canvas.clientHeight || window.innerHeight;
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  /* Узел ставим не в случайную точку экрана, а в область ввода,
   * на глаз по центру-правее: так дописанный текст визуально
   * продолжает фотографию, а не появляется из ниоткуда. */
  function addNode(x, y) {
    var w = canvas.clientWidth || window.innerWidth;
    var h = canvas.clientHeight || window.innerHeight;

    nodes.push({
      x: x === undefined ? w * 0.55 + (Math.random() - 0.5) * w * 0.25 : x,
      y: y === undefined ? h * 0.45 + (Math.random() - 0.5) * h * 0.3 : y,
      vx: (Math.random() - 0.5) * DRIFT,
      vy: (Math.random() - 0.5) * DRIFT
    });

    /* Старые узлы уходят первыми: сеть должна дышать, а не расти
     * бесконечно, иначе связей станет слишком много. */
    while (nodes.length > MAX_NODES) { nodes.shift(); }
  }

  /* Связи считаем и рисуем за один проход по парам: O(n²), но при
   * 70 узлах это меньше двух тысяч сравнений на кадр. */
  function countLinks() {
    var n = 0;
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var dx = nodes[i].x - nodes[j].x;
        var dy = nodes[i].y - nodes[j].y;
        if (dx * dx + dy * dy < LINK_DIST * LINK_DIST) { n++; }
      }
    }
    return n;
  }

  function updateCounters() {
    if (nodes.length !== lastNodes) {
      nodesOut.textContent = String(nodes.length);
      lastNodes = nodes.length;
    }
    var links = countLinks();
    if (links !== lastLinks) {
      linksOut.textContent = String(links);
      lastLinks = links;
    }
  }

  function draw() {
    var w = canvas.clientWidth || window.innerWidth;
    var h = canvas.clientHeight || window.innerHeight;
    ctx.clearRect(0, 0, w, h);

    var i, j;
    for (i = 0; i < nodes.length; i++) {
      for (j = i + 1; j < nodes.length; j++) {
        var dx = nodes[i].x - nodes[j].x;
        var dy = nodes[i].y - nodes[j].y;
        var d2 = dx * dx + dy * dy;
        if (d2 > LINK_DIST * LINK_DIST) { continue; }
        /* Прозрачность линии зависит от расстояния: чем ближе,
         * тем явнее. Так сеть читается как сеть, а не как паутина. */
        var a = 1 - Math.sqrt(d2) / LINK_DIST;
        ctx.strokeStyle = 'rgba(120, 210, 255, ' + (a * 0.38).toFixed(3) + ')';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(nodes[i].x, nodes[i].y);
        ctx.lineTo(nodes[j].x, nodes[j].y);
        ctx.stroke();
      }
    }

    for (i = 0; i < nodes.length; i++) {
      ctx.fillStyle = 'rgba(170, 230, 255, 0.85)';
      ctx.beginPath();
      ctx.arc(nodes[i].x, nodes[i].y, 2.2, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function step() {
    var w = canvas.clientWidth || window.innerWidth;
    var h = canvas.clientHeight || window.innerHeight;
    var i;
    for (i = 0; i < nodes.length; i++) {
      nodes[i].x += nodes[i].vx;
      nodes[i].y += nodes[i].vy;
      /* Отскок от краёв: узел уходит за край и возвращается сам,
       * чтобы не приходилось пересоздавать его в обработчике. */
      if (nodes[i].x < 0 || nodes[i].x > w) { nodes[i].vx = -nodes[i].vx; }
      if (nodes[i].y < 0 || nodes[i].y > h) { nodes[i].vy = -nodes[i].vy; }
    }
    draw();
    updateCounters();
  }

  var timer = null;

  function run() {
    if (!ctx || reduced) {
      /* Без анимации один статичный кадр: узлы всё равно видно,
       * просто они не двигаются. */
      if (ctx) { draw(); }
      updateCounters();
      return;
    }
    /* Кадр рисуем сразу, а не через 33 миллисекунды после первого
     * интервала: иначе после ввода сетка моргает пустотой. */
    if (ctx) { draw(); }
    if (timer !== null) { return; }
    timer = window.setInterval(step, 33);   /* около 30 кадров в секунду */
  }

  /* Событие input, а не keyup: вставка мышью, отмена действия
   * и ввод с экранной клавиатуры тоже обязаны добавлять узлы. */
  input.addEventListener('input', function () {
    var text = input.value;
    /* Длина строки и есть число узлов: узел на символ, ничего
     * сложнее. Символ, который стёрли, убирает и узел. */
    while (nodes.length < text.length) { addNode(); }
    while (nodes.length > text.length) { nodes.pop(); }
    /* Счётчики обновляем сразу, а не в следующем кадре: между
     * вводом и кадром проходит до 33 миллисекунд, и за это время
     * цифра успевает выглядеть «не сработавшей». */
    updateCounters();
    run();
  });

  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      input.value = '';
      nodes.length = 0;
      if (ctx) { draw(); }
      updateCounters();
      input.focus();
    });
  }

  if (pulseBtn) {
    pulseBtn.addEventListener('click', function () {
      var i;
      /* «Ещё строку»: ровная линия узлов поперёк экрана. Смысл
       * не в красоте, а в проверке, что сеть реагирует на событие,
       * а не висит мёртвой картинкой. */
      var w = canvas.clientWidth || window.innerWidth;
      for (i = 0; i < 14; i++) {
        addNode(w * (0.15 + 0.05 * i), (canvas.clientHeight || window.innerHeight) *
                 (0.25 + 0.35 * (i % 3) / 2));
      }
      /* Счётчики — сразу, по той же причине, что и при вводе. */
      updateCounters();
      run();
    });
  }

  window.addEventListener('resize', function () {
    if (!ctx) { return; }
    sizeCanvas();
    if (reduced) { draw(); } else { run(); }
  });

  /* Вкладку убрали в фон — анимацию останавливаем: она всё равно
   * не видна, но продолжает жечь батарею. Вернули — запускаем. */
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      if (timer !== null) { window.clearInterval(timer); timer = null; }
    } else {
      run();
    }
  });

  if (ctx) { sizeCanvas(); }
  updateCounters();
})();