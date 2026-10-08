/* Нова — горизонт кадра.
 *
 * Скрипт делает ровно одну вещь: переносит значение ползунка в
 * CSS-переменную --pan на корне документа. Всё остальное — сдвиг
 * кадра внутри полосы и положение розового зарева — делает CSS.
 * Разделение выбрано потому, что тогда скрипт остаётся на двадцати
 * строчках и его можно прочитать целиком, а CSS — единственное
 * место, где описано, как выглядит подача.
 *
 * Почему нужен скрипт вовсе: без него кадр стоит по центру и
 * страница всё равно читается. Скрипт не добавляет содержимого,
 * он только двигает уже показанное — поэтому его отсутствие не
 * ломает страницу, и на этом принципе построен весь файл: если
 * чего-то нет, выходим молча.
 *
 * Состояние намеренно не сохраняется в localStorage. Заглушка не
 * должна оставлять след в браузере и не должна при следующем
 * открытии показывать не то, что человек видел в каталоге.
 */
(function () {
  'use strict';

  // Зоны кадра. Порядок снизу вверх по object-position: 0 % — верх
  // кадра (небо и планета), 100 % — низ (вершины гор справа).
  // Границы стоят прямо здесь, а не в CSS, потому что подпись
  // обязана совпадать с тем, что показывает ползунок: если границы
  // разъедутся, подпись начнёт врать, а это хуже, чем её нет.
  var ZONES = [
    { until: 25, word: 'верх кадра: небо и планета' },
    { until: 50, word: 'верхняя половина: горизонт' },
    { until: 75, word: 'нижняя половина: сетка гор' },
    { until: 101, word: 'низ кадра: вершины справа' }
  ];

  var root = document.documentElement;
  var range = document.getElementById('pan');
  var out = document.getElementById('pan-out');
  var shot = document.getElementById('window');

  // Без разметки скрипту нечего делать. Выходим тихо: страница
  // остаётся читаемой, и это важнее любой мелкой поломки.
  if (!range || !out) { return; }

  function zoneWord(value) {
    for (var i = 0; i < ZONES.length; i++) {
      if (value < ZONES[i].until) { return ZONES[i].word; }
    }
    return ZONES[ZONES.length - 1].word;
  }

  function apply(raw) {
    var value = Math.min(100, Math.max(0, parseInt(raw, 10) || 0));
    // object-position по вертикали: 0 % — верх кадра в окне,
    // 100 % — низ. Ровно тот же порядок, что у ZONES.
    root.style.setProperty('--pan', value + '%');
    out.textContent = zoneWord(value) + ', ' + value + ' %';
    // Экранный диктор читает процент без смысла, поэтому смысл
    // дублируется в aria-valuetext. aria-live здесь не нужен и
    // даже вреден: при перетаскивании он тараторил бы значения.
    range.setAttribute('aria-valuetext',
                       zoneWord(value) + ', ' + value + ' процентов');
  }

  range.addEventListener('input', function () {
    apply(range.value);
  });

  // Клик и перетаскивание по самому снимку. Не замена ползунку, а
  // дополнение: на широкой полосе до неё легко дотянуться, и она
  // делает то же самое мышью. Слушатель один на оба события —
  // pointerdown начинает, pointermove продолжает только если
  // кнопка нажата (кнопку отпустили, чтобы не тянуть кадр
  // случайным проносом мимо полосы).
  if (shot) {
    var dragging = false;

    function panFromEvent(event) {
      var box = shot.getBoundingClientRect();
      if (box.height <= 0) { return; }
      // Верх окна — 0 %, низ — 100 %.
      var ratio = (event.clientY - box.top) / box.height;
      var value = Math.round(ratio * 100);
      range.value = String(value);
      apply(value);
    }

    shot.addEventListener('pointerdown', function (event) {
      dragging = true;
      // Захват указателя: без него pointermove на телефоне
      // прерывается, когда палец уходит за пределы полосы.
      if (shot.setPointerCapture && event.pointerId !== undefined) {
        try { shot.setPointerCapture(event.pointerId); } catch (e) { /* не критично */ }
      }
      panFromEvent(event);
    });

    shot.addEventListener('pointermove', function (event) {
      if (!dragging) { return; }
      panFromEvent(event);
    });

    // Отпускание ловим на окне: если палец увели за пределы
    // полосы, событие pointerup придёт сюда, а не элементу.
    window.addEventListener('pointerup', function () { dragging = false; });
    window.addEventListener('pointercancel', function () { dragging = false; });
  }

  // Начальное значение ставим один раз при старте: разметка уже
  // содержит value="50", но если ползунок трогали руками, подпись
  // должна совпадать с тем, что реально применено.
  apply(range.value);
})();
