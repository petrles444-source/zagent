/* Портфолио «ТЕРМИНАЛ» — поведение консоли.
 *
 * Страница работает и без этого файла: блоки и ссылки на месте, просто
 * не переключаются по командам. Поэтому весь скрипт — это переключение
 * блоков и набор текста в промпте, без единого обязательного элемента
 * управления.
 */
'use strict';

/* Команда → блок, который она открывает. Ключи совпадают с колонкой
 * команды в таблице, чтобы страницу можно было читать и не кликая. */
const COMMANDS = {
  help: 'commands',
  '?': 'commands',
  commands: 'commands',
  works: 'works',
  tools: 'works',
  keys: 'keys',
  howto: 'howto',
  notes: 'notes',
  status: 'boot',
};

const blocks = [...document.querySelectorAll('.block')];
const typed = document.querySelector('.typed');
const say = document.querySelector('.say');
const history = [];

/* Позиция в истории и признак того, что она открыта.
 *
 * Раньше оба состояния — «ввод ещё не открыт» и «дошли до самой старой
 * команды» — держались в одной переменной значением -1. Из-за этого
 * стрелка вверх, упёршаяся в начало, откатывалась назад к последней
 * команде: листание вперёд-назад работало через раз.
 */
let historyAt = 0;
let historyOpen = false;

/** Показать один блок и скрыть остальные. */
function show(id) {
  for (const block of blocks) {
    block.classList.toggle('off', block.id !== id);
  }
  if (id) {
    const target = document.getElementById(id);
    if (target) target.scrollIntoView({ block: 'start' });
  }
}

/** Написать текст в промпт. Разметку промпта не трогаем: курсор и
 * префикс должны остаться на месте, иначе после первого нажатия строка
 * теряет вид «guest@zagent:~$». */
function print(text) {
  if (typed) typed.textContent = text;
}

/** Показать ответ терминала — в отдельном элементе перед вводом.
 *
 * Ответ и ввод держатся раздельно намеренно. Когда ответ писался в то
 * же поле, следующая команда дописывалась к нему и получалось
 * «команда не найдена: zapros · help — списокsudo».
 */
function reply(text) {
  if (say) say.textContent = text;
  print('');
}

/** Выполнить команду. Возвращает текст для промпта.
 *
 * Текст возвращается, а не печатается сразу: иначе обработчик Enter
 * очищал бы промпт следом и стирал бы ответ об ошибке прежде, чем его
 * успели увидеть.
 */
function run(raw) {
  const line = raw.trim().toLowerCase();
  if (!line) return '';

  if (line === 'clear') {
    for (const block of blocks) block.classList.add('off');
    return '';
  }
  if (line === 'sudo') return 'sudo: нет. ключи всё равно на машине';
  if (COMMANDS[line]) {
    show(COMMANDS[line]);
    return '';
  }
  return 'команда не найдена: ' + line + '  ·  help — список';
}

/** Открыть историю и перейти по ней. direction = -1 вверх, +1 вниз. */
function walk(direction) {
  if (!history.length) return;
  if (!historyOpen) {
    // Из закрытого ввода вверх открывается последняя команда; вниз
    // идти некуда — внизу уже свежий пустой ввод.
    if (direction === 1) return;
    historyAt = history.length - 1;
    historyOpen = true;
  } else {
    // Упор в конец или в начало означает «стой на месте», а не переход
    // через край: иначе листание начинает прыгать на другой край.
    historyAt += direction;
    if (historyAt < 0) historyAt = 0;
    if (historyAt > history.length - 1) historyAt = history.length - 1;
  }
  print(history[historyAt]);
}

/* Клик по строке в таблице команд запускает её — приём, к которому
 * привыкаешь в документации. */
for (const row of document.querySelectorAll('.tbl tr')) {
  const name = row.querySelector('td.c');
  if (!name) continue;
  const command = name.textContent.trim();
  if (!COMMANDS[command] && command !== 'clear') continue;
  row.style.cursor = 'pointer';
  row.addEventListener('click', () => {
    history.push(command);
    historyOpen = false;
    reply(run(command));
  });
}

/* Клавиатура: ввод в промпте, стрелки — история, Ctrl+L — сброс,
 * Esc — наверх. Печатать имеет смысл, только когда ни одно поле не в
 * фокусе: иначе страница печатает поверх ввода в поле. */
document.addEventListener('keydown', (event) => {
  if (event.ctrlKey && event.key.toLowerCase() === 'l') {
    event.preventDefault();
    reply(run('clear'));
    return;
  }
  if (event.key === 'Escape') {
    event.preventDefault();
    window.scrollTo({ top: 0, behavior: 'smooth' });
    return;
  }
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
  if (!typed) return;

  if (event.key === 'Enter') {
    event.preventDefault();
    const line = typed.textContent;
    if (line.trim()) history.push(line);
    historyOpen = false;
    // Ответ терминала показывается рядом с промптом, а не занимает
    // поле ввода: иначе следующая команда допишется к нему.
    reply(run(line));
    return;
  }
  if (event.key === 'Backspace') {
    event.preventDefault();
    typed.textContent = typed.textContent.slice(0, -1);
    return;
  }
  if (event.key === 'ArrowUp') {
    event.preventDefault();
    walk(-1);
    return;
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault();
    walk(1);
    return;
  }
  /* Печатаем все одиночные символы, включая пробел: в промпте пробел
   * нужен не меньше букв. */
  if (event.key.length === 1) {
    event.preventDefault();
    // Рукописный ввод закрывает просмотр истории: дальше стрелка
    // вверх должна открывать последнюю выполненную команду, а не
    // продолжать листать с того места, где ввод остановился.
    historyOpen = false;
    typed.textContent += event.key;
  }
});