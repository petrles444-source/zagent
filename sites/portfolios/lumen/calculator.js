/* Калькулятор калорий для страницы LUMEN.
 *
 * Формула
 * -------
 * Базовый обмен (BMR) считается по Миффлину — Сан Жеору:
 *
 *   мужчины:  10·вес + 6.25·рост − 5·возраст + 5
 *   женщины:  10·вес + 6.25·рост − 5·возраст − 161
 *
 * Вес в килограммах, рост в сантиметрах, возраст в годах. Это
 * оценочная величина: она не знает про телосложение, мышцы, возраст
 * и не заменяет врача. Поэтому ниже написано именно «оценка».
 *
 * Прочность расчёта
 * -----------------
 * Всё считается на числах, полученных из полей. Ввод не проходит через
 * `eval` и не собирается в строку: строка собирается только для вывода
 * и там экранируется. Значение из поля — единственное, что попадает
 * в арифметику, поэтому «10 + 5; fetch(...)» остаётся числом NaN и
 * просто не считается.
 */
'use strict';

/* Коэффициенты активности. Подписи описательными словами: число само
 * по себе ни о чём не говорит, а «лёгкая» — понятно. */
const ACTIVITY = [
  ['1.2', 'Сидячая: работа за столом, без тренировок'],
  ['1.375', 'Лёгкая: 1–3 тренировки в неделю'],
  ['1.55', 'Умеренная: 3–5 тренировок'],
  ['1.725', 'Высокая: 6–7 тренировок'],
  ['1.9', 'Очень высокая: физическая работа плюс тренировки'],
];

/* Границы индекса массы тела — как их определяет ВОЗ. */
function bmiClass(bmi) {
  if (bmi < 16) return ['bmi-bad', 'выраженный дефицит массы'];
  if (bmi < 18.5) return ['bmi-warn', 'ниже нормы'];
  if (bmi < 25) return ['bmi-ok', 'норма'];
  if (bmi < 30) return ['bmi-warn', 'избыточная масса'];
  if (bmi < 35) return ['bmi-bad', 'ожирение I степени'];
  if (bmi < 40) return ['bmi-bad', 'ожирение II степени'];
  return ['bmi-bad', 'ожирение III степени'];
}

/* Всё, что показываем, проходит через эту функцию. Нас��аиваем прямое
 * присваивание — защита от того, чтобы значение из ответа сервера или
 * из поля стало разметкой. */
function esc(value) {
  const div = document.createElement('div');
  div.textContent = String(value);
  return div.innerHTML;
}

/* Число из поля. Возвращает null, если значение не число или поле пусто:
 * отличать «пользователь не ввёл» от «ввёл ерунду» нужно, чтобы
 * подсказка была разной. */
function readNumber(id) {
  const raw = (document.getElementById(id) || {}).value;
  if (raw === undefined || raw === null) return null;
  const text = String(raw).trim().replace(',', '.');
  if (!text) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/* Проверка правдоподобия. Возвращает текст проблемы или '' если всё в
 * порядке: границы здесь не придирки, а защита от вывода вида
 * «калорий 31880» из-за опечатки в весе. */
function validate({ age, weight, height }) {
  if (age === null) return 'Укажите возраст.';
  if (weight === null) return 'Укажите вес.';
  if (height === null) return 'Укажите рост.';
  if (age < 10 || age > 100) return 'Возраст должен быть от 10 до 100 лет.';
  if (weight < 25 || weight > 300) return 'Вес должен быть от 25 до 300 кг.';
  if (height < 120 || height > 230) return 'Рост должен быть от 120 до 230 см.';
  return '';
}

function calculate() {
  const male = document.getElementById('cGender').value === 'male';
  const age = readNumber('cAge');
  const weight = readNumber('cWeight');
  const height = readNumber('cHeight');
  const activity = Number(document.getElementById('cActivity').value);
  const deficit = Number(document.getElementById('cDeficit').value);

  const out = document.getElementById('calcOut');
  const warn = document.getElementById('calcWarn');

  const problem = validate({ age, weight, height });
  if (problem) {
    out.innerHTML = '';
    warn.textContent = problem;
    return;
  }

  const bmr = 10 * weight + 6.25 * height - 5 * age + (male ? 5 : -161);
  const tdee = bmr * activity;
  const target = Math.round(tdee * (1 - deficit));

  /* Белок и жиры — от веса, углеводы — остатком от калорий. Порядок
   * именно такой: белок и жиры задаются граммами на килограмм, а
   * углеводы должны уместиться в оставшийся бюджет. Если остаток
   * отрицательный, показываем ноль и предупреждаем — иначе в сумме
   * получится больше, чем цель. */
  const protein = Math.round(weight * 1.9);
  const fat = Math.round(weight * 0.85);
  const carbsRaw = (target - protein * 4 - fat * 9) / 4;
  const carbs = Math.max(0, Math.round(carbsRaw));

  const bmi = weight / Math.pow(height / 100, 2);
  const [bmiClassName, bmiWord] = bmiClass(bmi);

  const pPct = Math.round(protein * 4 / target * 100) || 0;
  const fPct = Math.round(fat * 9 / target * 100) || 0;
  const cPct = Math.max(0, 100 - pPct - fPct);

  out.innerHTML = [
    '<div class="calc-nums">',
    '  <div class="calc-num"><span class="k">Индекс массы</span>',
    '    <span class="v ' + bmiClassName + '">' + bmi.toFixed(1) + '</span>',
    '    <span class="hint">' + esc(bmiWord) + '</span></div>',
    '  <div class="calc-num"><span class="k">Базовый обмен</span>',
    '    <span class="v">' + Math.round(bmr) + '</span>',
    '    <span class="hint">ккал в покое</span></div>',
    '  <div class="calc-num"><span class="k">Поддержание веса</span>',
    '    <span class="v">' + Math.round(tdee) + '</span>',
    '    <span class="hint">с учётом активности</span></div>',
    '  <div class="calc-num is-target"><span class="k">Цель</span>',
    '    <span class="v">' + esc(target) + '</span>',
    '    <span class="hint">ккал при дефиците ' + esc(deficit * 100) + '%</span></div>',
    '</div>',
    '<div class="macros">',
    '  <div class="macros-head"><span>белки · жиры · углеводы</span>',
    '    <span>по ' + esc(weight) + ' кг вашего веса</span></div>',
    '  <div class="bar-macros">',
    '    <i class="p" style="width:' + pPct + '%"></i>',
    '    <i class="f" style="width:' + fPct + '%"></i>',
    '    <i class="c" style="width:' + cPct + '%"></i>',
    '  </div>',
    '  <div class="macro-row"><b>белки</b><span>1,9 г/кг</span>',
    '    <span class="kcal">' + esc(protein) + ' г · ' + esc(pPct) + '% · ' + esc(protein * 4) + ' ккал</span></div>',
    '  <div class="macro-row"><b>жиры</b><span>0,85 г/кг</span>',
    '    <span class="kcal">' + esc(fat) + ' г · ' + esc(fPct) + '% · ' + esc(fat * 9) + ' ккал</span></div>',
    '  <div class="macro-row"><b>углеводы</b><span>остаток</span>',
    '    <span class="kcal">' + esc(carbs) + ' г · ' + esc(cPct) + '% · ' + esc(carbs * 4) + ' ккал</span></div>',
    '</div>',
  ].join('\n');

  /* Нижняя граница. Не «правило», а ограничение самого расчёта:
   * опуститься ниже нельзя, иначе цифры перестают значить хоть
   * что-нибудь. */
  const notes = [];
  if (target < 1200) {
    notes.push('Цель ниже 1200 ккал — это уже не дефицит, а голодание. '
      + 'Так считать нельзя: организм снижает расход, и через пару недель '
      + 'цифры перестают иметь смысл.');
  }
  if (carbsRaw < 0) {
    notes.push('Белка и жиров по указанным нормам получается больше, чем '
      + 'самой цели. Поднимите калории или снизьте долю белка — иначе '
      + 'углеводов в рационе не останется вовсе.');
  }
  if (bmi < 18.5) {
    notes.push('Индекс массы ниже нормы. Дефицит при таком показателе '
      + 'обычно не нужен — обсудите это с врачом, а не с калькулятором.');
  }
  warn.textContent = notes.join(' ');
}

document.addEventListener('DOMContentLoaded', function () {
  /* Список активности собираем из массива, а не пишем в разметке:
   * иначе пришлось бы держать две копии одного и того же — здесь и
   * в разметке, — и они разошлись бы при первой же правке. */
  const select = document.getElementById('cActivity');
  if (select && !select.options.length) {
    for (const [value, label] of ACTIVITY) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      select.appendChild(option);
    }
  }

  const deficit = document.getElementById('cDeficit');
  const shown = document.getElementById('cDeficitValue');
  const target = document.getElementById('cTargetHint');

  function syncSlider() {
    shown.textContent = deficit.value + '%';
  }

  /* Подпись цели обновляется на ходу: человек видит, к чему ведёт
   * ползунок, ещё до нажатия кнопки. Считаем здесь же — формула
   * вынесена в calculate(), но для подсказки достаточно повторить
   * три строки арифметики, а не гонять полный расчёт. */
  function syncTarget() {
    const male = document.getElementById('cGender').value === 'male';
    const age = readNumber('cAge');
    const weight = readNumber('cWeight');
    const height = readNumber('cHeight');
    if (age === null || weight === null || height === null) {
      target.textContent = '';
      return;
    }
    const bmr = 10 * weight + 6.25 * height - 5 * age + (male ? 5 : -161);
    const tdee = bmr * Number(document.getElementById('cActivity').value);
    target.textContent = '≈ ' + Math.round(tdee * (1 - deficit.value / 100))
      + ' ккал';
  }

  for (const id of ['cGender', 'cAge', 'cWeight', 'cHeight', 'cActivity']) {
    const element = document.getElementById(id);
    if (element) element.addEventListener('input', syncTarget);
    if (element && element.tagName === 'SELECT') {
      element.addEventListener('change', syncTarget);
    }
  }

  deficit.addEventListener('input', function () {
    syncSlider();
    syncTarget();
  });

  document.getElementById('calcBtn').addEventListener('click', calculate);

  /* Расчёт на странице сразу: пустой калькулятор, который начинает
   * работать только после нажатия, выглядит сломанным. */
  syncSlider();
  syncTarget();
  calculate();
});