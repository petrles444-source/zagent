// Змейка на canvas с хранением рекорда.
//
// Весь смысл файла — в трёх местах, которые обычно делают неправильно:
//
// 1. **Очередь поворотов.** Если игрок быстро жмёт «ввер��» и «влево» до хода
//    таймера, а код меняет направление сразу, змейка разворачивается сама в
//    себя и умирает на ровном месте. П��этому повороты складываются в очередь,
//    и за ход бер��тся ровно один.
//
// 2. **Единый цикл на requestAnimationFrame.** Время идёт через накопленный
//    счётчик, а не через setInterval: два таймера расходятся по кадрам, и на
//    144 Гц игра шла бы вдвое быстрее, чем на 60.
//
// 3. **Хвост отнимается до проверки столкновения.** На клетку, где только что
//    был хвост, шагнуть можно — змейка её освободила. Проверка по всему телу
//    без этого ломает игру на клетку.
//
// Запуск: открой index.html в браузере.

const COLS = 20;
const ROWS = 20;
const CELL = 24; // размер клетки в CSS-пикселях

// Сколько миллисекунд на шаг в начале; уменьшается при росте счёта.
const BASE_STEP_MS = 180;
const MIN_STEP_MS = 70;
const SPEED_STEP_SCORE = 5;

const KEYS = {
  ArrowUp: 'up', ArrowDown: 'down',
  ArrowLeft: 'left', ArrowRight: 'right',
  w: 'up', s: 'down', a: 'left', d: 'right',
  ц: 'up', ы: 'down', ф: 'left', в: 'right',
};

// Противоположные направления нельзя разворачивать в себя.
const OPPOSITE = { up: 'down', down: 'up', left: 'right', right: 'left' };

const DIRECTIONS = {
  up: [0, -1],
  down: [0, 1],
  left: [-1, 0],
  right: [1, 0],
};

const RECORD_KEY = 'snake.record';

class Snake {
  constructor(canvas, scoreOut, recordOut) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.scoreOut = scoreOut;
    this.recordOut = recordOut;
    this.record = this.loadRecord();

    // Повороты ждут своего хода. Именно из-за этой очереди змейка не
    // разворачивается в себя при быстрых нажатиях.
    this.turns = [];
    this.last = 0;

    this.reset();
  }

  // ------------------------------------------------------------ состояние

  reset() {
    this.snake = [{ x: ROWS >> 1, y: COLS >> 1 }];
    this.direction = 'right';
    this.turns = [];
    this.score = 0;
    this.over = false;
    this.paused = false;
    this.accum = 0;
    this.food = this.freeSpot();
    this.paintText();
  }

  // Свободная клетка. При полностью забитом поле возвращаем (0, 0): поле,
  // забитое змейкой, — это победа, а не ошибка.
  freeSpot() {
    const taken = new Set(this.snake.map((cell) => cell.y * COLS + cell.x));
    const free = [];
    for (let y = 0; y < ROWS; y += 1) {
      for (let x = 0; x < COLS; x += 1) {
        if (!taken.has(y * COLS + x)) free.push({ x, y });
      }
    }
    if (!free.length) return { x: 0, y: 0 };
    return free[Math.floor(Math.random() * free.length)];
  }

  get stepMs() {
    return Math.max(MIN_STEP_MS, BASE_STEP_MS - Math.floor(this.score / SPEED_STEP_SCORE) * 10);
  }

  // ---------------------------------------------------------------- ввод

  // Поворот в противоположную сторону отбрасывается: иначе змейка входит сама
  // в себя. Очередь ограничена двумя: больше нажатий за один ход всё равно
  // не сыграет, а неограниченная очередь даёт задержку ввода.
  turn(name) {
    const last = this.turns.length ? this.turns[this.turns.length - 1] : this.direction;
    if (name === last || OPPOSITE[name] === last) return;
    if (this.turns.length < 2) this.turns.push(name);
  }

  togglePause() {
    if (!this.over) this.paused = !this.paused;
  }

  // ----------------------------------------------------------------- ход

  tick() {
    if (this.turns.length) this.direction = this.turns.shift();
    const [dx, dy] = DIRECTIONS[this.direction];
    const head = this.snake[0];
    const next = { x: head.x + dx, y: head.y + dy };

    if (next.x < 0 || next.x >= COLS || next.y < 0 || next.y >= ROWS) {
      this.lose();
      return;
    }

    // Хвост отнимается ДО проверки столкновения: на его бывшую клетку
    // шагнуть можно, змейка её уже освободила.
    const body = this.snake.slice(0, -1);
    if (body.some((cell) => cell.x === next.x && cell.y === next.y)) {
      this.lose();
      return;
    }

    this.snake.unshift(next);

    if (next.x === this.food.x && next.y === this.food.y) {
      this.score += 1;
      if (this.score > this.record) {
        this.record = this.score;
        this.saveRecord();
      }
      // Еда не исчезает: хвост не отнималось, поле не забилось.
      this.food = this.freeSpot();
    } else {
      this.snake.pop();
    }

    this.paintText();
  }

  lose() {
    this.over = true;
    this.paintText();
  }

  // ---------------------------------------------------------------- цикл

  // Один кадр. Шаг делается по накопленному времени, поэтому скорость игры
  // не зависит от частоты кадров.
  frame(now) {
    if (this.last === 0) this.last = now;
    const delta = now - this.last;
    this.last = now;

    if (!this.paused && !this.over) {
      this.accum += delta;
      // Долгий простой (вкладка была свёрнута) не приводит к пачке шагов:
      // за один кадр делаем ровно один, а остальное время просто сбрасываем.
      if (this.accum > this.stepMs) this.accum = this.stepMs;
      if (this.accum >= this.stepMs) {
        this.accum -= this.stepMs;
        this.tick();
      }
    }

    this.draw();
    requestAnimationFrame(this.frame.bind(this));
  }

  // ------------------------------------------------------------ отрисовка

  draw() {
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;

    ctx.fillStyle = '#11151c';
    ctx.fillRect(0, 0, w, h);

    ctx.fillStyle = '#e5484d';
    ctx.fillRect(this.food.x * CELL + 6, this.food.y * CELL + 6, CELL - 12, CELL - 12);

    for (let i = 0; i < this.snake.length; i += 1) {
      const cell = this.snake[i];
      // Голова светлее хвоста: положение видно с первого хода.
      ctx.fillStyle = i === 0 ? '#30a46c' : '#2a875a';
      ctx.fillRect(cell.x * CELL + 1, cell.y * CELL + 1, CELL - 2, CELL - 2);
    }

    if (this.paused || this.over) {
      ctx.fillStyle = 'rgba(8, 11, 16, .78)';
      ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = '#f5f7fa';
      ctx.textAlign = 'center';
      ctx.font = '600 22px system-ui, sans-serif';
      ctx.fillText(this.paused ? 'Пауза — пробел' : 'Игра окончена', w / 2, h / 2 - 6);
      ctx.font = '14px system-ui, sans-serif';
      ctx.fillText('Нажмите R, чтобы начать заново', w / 2, h / 2 + 22);
    }
  }

  paintText() {
    this.scoreOut.textContent = String(this.score);
    this.recordOut.textContent = String(this.record);
  }

  // -------------------------------------------------------------- рекорд

  // Приватный режим браузера запрещает localStorage. Игра обязана работать
  // и без рекорда — просто не сохраняет его.
  loadRecord() {
    try {
      return Number(localStorage.getItem(RECORD_KEY)) || 0;
    } catch {
      return 0;
    }
  }

  saveRecord() {
    try {
      localStorage.setItem(RECORD_KEY, String(this.record));
    } catch {
      /* без сохранения игра всё равно работает */
    }
  }
}

function start() {
  const canvas = document.getElementById('board');
  canvas.width = COLS * CELL;
  canvas.height = ROWS * CELL;

  const game = new Snake(canvas, document.getElementById('score'),
                         document.getElementById('record'));

  document.addEventListener('keydown', (event) => {
    const name = KEYS[event.key] || KEYS[event.key.toLowerCase()];
    if (name) {
      event.preventDefault();
      game.turn(name);
      return;
    }
    if (event.key === ' ') {
      event.preventDefault();
      game.togglePause();
      return;
    }
    if (['r', 'R', 'к', 'К'].includes(event.key)) game.reset();
  });

  const button = document.getElementById('restart');
  if (button) button.addEventListener('click', () => game.reset());

  // Возврат на вкладку не должен резко ускорить игру за счёт накопленного
  // времени, поэтому счётчик обнуляется.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) game.last = 0;
  });

  requestAnimationFrame(game.frame.bind(game));

  // Доступ из консоли браузера — удобно проверять состояние при отладке.
  window.game = game;
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', start);
} else {
  start();
}