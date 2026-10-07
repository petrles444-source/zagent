"""Интерфейс zagent: три панели с перетаскиваемыми разделителями.

Раскладка как у взрослых IDE-агентов (OpenCode, DeepSeek Harness):

    слева    модели и воркспейсы, можно прикрепить файл к задаче
    центр    чат с агентом, журнал шагов, очередь
    справа   просмотр файлов воркспейса

Разделители перетаскиваются мышью, ширина панелей сохраняется в localStorage.
Тёмная тема, без внешних зависимостей: всё рисуется на div и превью-файлы.

Модели — главная вкладка: здесь видно provider id, base URL и ключ каждого
шлюза, а также готовые инструкции для OpenCode, DeepSeek, Codex, Zed и Cline.
Кнопка «Скопировать» кладёт конфиг в буфер обмена целиком.
"""

UI_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>zagent</title>
<!-- Шрифты Geist из ref-design. Подключаются по сети, но без них интерфейс
     остаётся рабочим: --sans и --mono в :root указывают на системные. -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
<script>
// Применяем тему до первой отрисовки, иначе при загрузке моргает тёмная
// тема и потом переключается на сохранённую. Обёртка в try: приватный режим
// браузера запрещает localStorage, и страница должна работать без него.
(function () {
  var t = null;
  try { t = JSON.parse(localStorage.getItem('zagent.theme') || 'null'); } catch (e) {}
  if (!t && window.matchMedia &&
      matchMedia('(prefers-color-scheme: light)').matches) t = 'light';
  document.documentElement.dataset.theme = t || 'dark';
})();
</script>
<style>
/* ============================================================
   ТЕМЫ
   Каждая тема переопределяет только токены — компоненты ниже
   не знают про темы и берут цвет из переменной. Поэтому новая
   тема — это 15 строк, а не правка всего CSS.
   ============================================================ */

/* Тёмная — исходная */
:root, [data-theme="dark"] {
  --bg:#0d1014; --panel:#141922; --panel2:#1a2029; --edge:#242c38;
  --text:#e4e8ef; --muted:#8792a4; --dim:#5f6b7d;
  --accent:#3b82f6; --accent-dim:#1e3a6d; --accent-text:#fff;
  --ok:#22c55e; --warn:#f59e0b; --bad:#ef4444; --info:#60a5fa;
  --shadow:0 12px 32px rgba(0,0,0,.45);
  --glow:0 0 0 1px var(--edge), 0 0 18px -6px var(--accent);
  --radius:9px;
  /* Граница, которой рисуют разделители и полосу прогресса.
     Объявлена через --edge, чтобы не расходилась с темой: раньше
     переменной не существовало вовсе, и border вырождался в
     currentColor, а фон трека — в прозрачность. */
  --line: var(--edge);
}

/* Чёрная — OLED, края сливаются с фоном окна */
[data-theme="black"] {
  --bg:#000; --panel:#08090b; --panel2:#101216; --edge:#1c2026;
  --text:#eef1f5; --muted:#8b93a1; --dim:#666e7a;
  --accent:#4f8ef7; --accent-dim:#17305c; --accent-text:#000;
  --ok:#22c55e; --warn:#f59e0b; --bad:#ef4444; --info:#60a5fa;
  --shadow:0 12px 32px rgba(0,0,0,.7);
  --glow:0 0 0 1px #23282f, 0 0 20px -6px var(--accent);
  --radius:10px;
}

/* Светлая */
[data-theme="light"] {
  --bg:#f7f8fa; --panel:#fff; --panel2:#f2f4f7; --edge:#dfe3ea;
  --text:#141920; --muted:#5c6673; --dim:#8a94a2;
  --accent:#2563eb; --accent-dim:#dbe7ff; --accent-text:#fff;
  --ok:#15a34a; --warn:#c2740a; --bad:#dc2626; --info:#2563eb;
  --shadow:0 10px 28px rgba(16,24,40,.10);
  --glow:0 0 0 1px #c3d8fb, 0 0 16px -6px var(--accent);
  --radius:9px;
}

/* Синяя — холодный деловой */
[data-theme="blue"] {
  --bg:#0a1220; --panel:#0f1b2e; --panel2:#152438; --edge:#1e3350;
  --text:#dce8f7; --muted:#7e9ab8; --dim:#587494;
  --accent:#38bdf8; --accent-dim:#0c3d55; --accent-text:#04121f;
  --ok:#2dd4a7; --warn:#fbbf24; --bad:#f87171; --info:#38bdf8;
  --shadow:0 12px 32px rgba(0,0,0,.5);
  --glow:0 0 0 1px #1e3a5f, 0 0 20px -6px var(--accent);
  --radius:9px;
}

/* Серая — максимально спокойная, без цвета */
[data-theme="gray"] {
  --bg:#141414; --panel:#1b1b1b; --panel2:#232323; --edge:#2e2e2e;
  --text:#ededed; --muted:#9a9a9a; --dim:#6e6e6e;
  --accent:#c9c9c9; --accent-dim:#3a3a3a; --accent-text:#141414;
  --ok:#8fce8f; --warn:#d9c07a; --bad:#e88b8b; --info:#b5b5b5;
  --shadow:0 12px 30px rgba(0,0,0,.5);
  --glow:0 0 0 1px #333, 0 0 16px -6px #c9c9c9;
  --radius:8px;
}

:root {
  /* Geist подключается ссылкой выше; без сети отдаём системный — интерфейс
     остаётся читаемым, поэтому font-family перечисляет запасные. */
  --sans:"Geist",-apple-system,"Segoe UI",system-ui,"Helvetica Neue",Arial,sans-serif;
  --mono:"Geist Mono",ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
}
* { box-sizing:border-box; margin:0; }
html,body { height:100%; }
body {
  background:var(--bg); color:var(--text); overflow:hidden;
  font:13.5px/1.55 var(--sans);
  /* Перехода на фоне здесь намеренно нет: при частой смене темы анимация
     не успевает завершиться, и страница остаётся в цвете прошлой темы —
     выглядит как «тема не применилась». Переключение мгновенное и надёжное. */
}
button { font:inherit; cursor:pointer; border:0; background:none; color:inherit; }
input,select,textarea { font:inherit; background:var(--panel2); color:var(--text);
  border:1px solid var(--edge); border-radius:6px; padding:6px 9px; outline:none;
  transition:border-color .15s ease,box-shadow .15s ease; }
input:focus,select:focus,textarea:focus {
  border-color:var(--accent); box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 18%,transparent);
}
textarea { resize:none; width:100%; font-family:inherit; }
::-webkit-scrollbar { width:9px; height:9px; }
::-webkit-scrollbar-thumb { background:var(--edge); border-radius:5px; }
::-webkit-scrollbar-thumb:hover { background:var(--dim); }
::-webkit-scrollbar-track { background:transparent; }

/* ============================================================
   КОМПОНЕНТЫ
   Взяты из выбранных эффектов: кольцевой спиннер, полосы прогресса,
   мерцающий текст, бейджи статуса, переключатель iOS, карточка со свечением.
   Каждый компонент использует токены темы, а не собственные цвета.
   ============================================================ */

/* \u0420\u0430\u0441\u043a\u0440\u044b\u0432\u0430\u044e\u0449\u0438\u0439\u0441\u044f \u0431\u043b\u043e\u043a: \u0437\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a \u0432\u0441\u0435\u0433\u0434\u0430 \u0432\u0438\u0434\u0435\u043d, \u0442\u0435\u043b\u043e \u2014 \u043f\u043e \u043a\u043b\u0438\u043a\u0443.
   \u0421\u043f\u0438\u0441\u043e\u043a \u043c\u043e\u0434\u0435\u043b\u0435\u0439 \u043e\u0431\u044f\u0437\u0430\u043d \u0431\u044b\u0442\u044c \u0432\u0438\u0434\u0435\u043d \u0441\u0440\u0430\u0437\u0443: \u0440\u0430\u043d\u044c\u0448\u0435 \u043f\u0430\u043d\u0435\u043b\u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u043e\u043a
   \u0437\u0430\u043d\u0438\u043c\u0430\u043b\u0438 \u0432\u0435\u0440\u0445 \u0432\u043a\u043b\u0430\u0434\u043a\u0438 \u0438 \u043e\u0442\u043e\u0434\u0432\u0438\u0433\u0430\u043b\u0438 \u0435\u0433\u043e \u0432\u043d\u0438\u0437. */
.fold { border-top:1px solid var(--edge); margin-top:6px; }
.foldHead {
  display:flex; align-items:center; gap:8px; width:100%;
  padding:9px 12px; background:none; border:0; cursor:pointer;
  font:inherit; font-size:12.5px; font-weight:600; color:var(--muted);
  text-align:left;
}
.foldHead:hover { color:var(--text); background:color-mix(in srgb,var(--accent) 6%,transparent); }
.foldHead:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
.foldIc { width:12px; display:inline-block; font-size:10px; color:var(--dim); }
.foldBody { padding:2px 0 10px; }
/* Без этого атрибута свернутый блок всё равно занимает место: [hidden]
   в CSS браузера перебивается любым display из класса. */
.foldBody[hidden] { display:none !important; }

/* \u041f\u043e\u0434\u0441\u043a\u0430\u0437\u043a\u0430 \u0432\u043d\u0443\u0442\u0440\u0438 \u0431\u043b\u043e\u043a\u0430: \u0437\u0430\u0447\u0435\u043c\u0443 \u043e\u043d \u043d\u0443\u0436\u0435\u043d. \u0418\u043d\u0430\u0447\u0435
   \u043d\u0435\u043f\u043e\u043d\u044f\u0442\u043d\u043e, \u0447\u0442\u043e \u043e\u0442\u043a\u0440\u044b\u0432\u0430\u0442\u044c. */
.hintBlock {
  margin:0 12px 8px; padding:8px 10px; font-size:12px; line-height:1.5;
  color:var(--muted); background:var(--panel2);
  border:1px solid var(--edge); border-radius:var(--radius);
}

/* \u0412\u044b\u0431\u043e\u0440 \u0440\u0435\u0436\u0438\u043c\u0430 \u0438 \u043c\u043e\u0434\u0435\u043b\u0438: \u0433\u043b\u0430\u0432\u043d\u044b\u0439 \u044d\u043b\u0435\u043c\u0435\u043d\u0442 \u0432\u043a\u043b\u0430\u0434\u043a\u0438, \u043f\u043e\u044d\u0442\u043e\u043c\u0443
   \u0440\u0430\u043c\u043a\u043e\u0439 \u0438 \u043f\u043e\u0434\u043f\u0438\u0441\u044c\u044e, \u0430 \u043d\u0435 \u043f\u0440\u044f\u0447\u0435\u043d \u0441\u0435\u0440\u0435\u0434 \u043e\u0442 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0439. */
.modePick {
  margin:10px 12px 8px; padding:10px;
  border:1px solid var(--edge); border-radius:calc(var(--radius) + 4px);
  background:var(--panel2);
}
.modeNote { margin-top:8px; font-size:12.5px; line-height:1.5; color:var(--muted); }
.modeNote b { color:var(--text); font-family:var(--mono); font-size:11.5px; }
.warnText { color:var(--warn); }
.linkish {
  cursor:pointer; color:var(--accent); text-decoration:underline;
  text-underline-offset:2px;
}
.linkish:hover { filter:brightness(1.15); }

/* \u0421\u0442\u0440\u043e\u043a\u0430 \u0432\u044b\u0431\u043e\u0440\u0430 \u043c\u043e\u0434\u0435\u043b\u0438: \u0432\u0441\u044f \u0441\u0442\u0440\u043e\u043a\u0430 \u043a\u043b\u0438\u043a\u0430\u0431\u0435\u043b\u044c\u043d\u0430, \u043f\u043e\u044d\u0442\u043e\u043c\u0443 \u043e\u043d\u0430 \u0448\u0438\u0440\u0435 \u043e\u0431\u044b\u0447\u043d\u043e\u0433\u043e \u0441\u043f\u0438\u0441\u043a\u0430.
   \u041a\u0440\u0443\u0433 \u0441\u043b\u0435\u0432\u0430 \u043f\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0435\u0442, \u0447\u0442\u043e \u0432\u044b\u0431\u0440\u0430\u043d\u0430. */
.mrow {
  display:flex; align-items:center; gap:8px;
  padding:7px 12px; cursor:pointer;
  border-left:2px solid transparent;
}
.mrow:hover { background:color-mix(in srgb,var(--accent) 8%,transparent); }
.mrow.on {
  background:color-mix(in srgb,var(--accent) 12%,transparent);
  border-left-color:var(--accent);
}
.mrow.on .nm { color:var(--text); font-weight:600; }
.mrow .nm { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.mrow .gw { max-width:88px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.mrow .radio { color:var(--dim); font-size:11px; width:10px; flex-shrink:0; }
.mrow.on .radio { color:var(--accent); }

/* \u041f\u0440\u043e\u0441\u043c\u043e\u0442\u0440 \u0444\u0430\u0439\u043b\u0430: \u0448\u0430\u043f\u043a\u0430 \u0441 \u043f\u0443\u0442\u0451\u043c \u0438 \u043a\u043d\u043e\u043f\u043a\u0430\u043c\u0438. */
.fhead {
  display:flex; align-items:center; gap:8px; padding:6px 10px;
  border-bottom:1px solid var(--edge);
  position:sticky; top:0; background:var(--panel); z-index:2;
}
.fhead .fn {
  font-family:var(--mono); font-size:11.5px; color:var(--text);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.fcrumbs {
  display:flex; align-items:center; gap:2px; flex-wrap:wrap;
  padding:6px 10px; border-bottom:1px solid var(--edge);
  font-size:12px; background:var(--panel);
}
.crumb { cursor:pointer; color:var(--muted); padding:1px 3px; border-radius:4px; }
.crumb:hover { color:var(--text); background:color-mix(in srgb,var(--accent) 10%,transparent); }
.crumb.on { color:var(--text); font-weight:600; }
.sep { color:var(--dim); }

/* \u041a\u0430\u0440\u0442\u0438\u043d\u043a\u0430 \u043f\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0435\u0442\u0441\u044f \u0432 \u043d\u0430\u0442\u0443\u0440\u0430\u043b\u044c\u043d\u044b\u0439 \u0432\u0435\u043b\u0438\u0447\u0438\u043d\u0435, \u043d\u043e \u043d\u0435 \u0448\u0438\u0440\u0435 \u043f\u0430\u043d\u0435\u043b\u0438. */
.imgWrap { padding:12px; text-align:center; }
.imgWrap img {
  max-width:100%; height:auto; border-radius:var(--radius);
  border:1px solid var(--edge);
}

pre.code {
  margin:0; padding:10px 12px;
  font-family:var(--mono); font-size:12px; line-height:1.5;
  white-space:pre-wrap; word-break:break-word;
}

.pheadTitle { font-weight:600; font-size:13px; }

/* Выбор модели у поля ввода: главное место, где видно, кто будет выполнять
   задачу. Раньше это было на отдельной вкладке, и режим не был виден
   в момент отправки. */
.modelRow {
  display:flex; align-items:center; gap:8px; padding:2px 0 5px;
}

.mBadge {
  display:inline-flex; align-items:center; gap:7px;
  padding:5px 11px; cursor:pointer; font:inherit; font-size:12.5px;
  background:var(--panel2); color:var(--text);
  border:1px solid var(--edge); border-radius:99px;
  max-width:340px;
}
.mBadge:hover { border-color:var(--accent); }
.mBadge:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
.mBadge .kind {
  color:var(--accent); font-weight:700; font-size:10.5px;
  text-transform:uppercase; letter-spacing:.4px;
}
.mBadge .nm {
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  font-family:var(--mono); font-size:11.5px;
}
.mBadge .caret { color:var(--dim); font-size:9px; }

/* Выпадающий список моделей под полем ввода. */
#modelPick {
  border:1px solid var(--edge); border-radius:var(--radius);
  background:var(--panel); margin-bottom:6px; overflow:hidden;
  box-shadow:var(--shadow);
}
#modelPick[hidden] { display:none; }

/* Выбор режима работы — рядом с моделью, потому что оба определяют, как
   пойдёт задача. */
#modePick {
  border:1px solid var(--edge); border-radius:var(--radius);
  background:var(--panel); margin-bottom:6px; overflow:hidden;
  box-shadow:var(--shadow);
}
#modePick[hidden] { display:none; }
.modeList { max-height:330px; overflow:auto; }
.modeCard { padding:9px 11px; border-bottom:1px solid var(--edge); cursor:pointer; }
.modeCard:last-child { border-bottom:none; }
.modeCard:hover { background:color-mix(in srgb,var(--accent) 8%,transparent); }
.modeCard.on { background:color-mix(in srgb,var(--ok) 10%,var(--panel)); }
.mcHead { font-size:13px; font-weight:600; display:flex; gap:8px;
  align-items:center; }
.mcOn { color:var(--ok); font-size:10.5px; font-weight:700;
  border:1px solid var(--ok); border-radius:4px; padding:0 4px; }
.mcNote { color:var(--muted); font-size:12px; margin-top:3px; }
.mcWarn { color:var(--warn); font-size:11.5px; margin-top:4px; }
#modeBtn.on { border-color:var(--ok); color:var(--ok); }

/* План роя: список занятых аккаунтов и резерва. */
.herdBox { margin: 0 0 8px; }
.herdBox:empty { display: none; }
.herdGroup {
  font-size:11px; color:var(--dim); text-transform:uppercase;
  letter-spacing:.04em; margin:6px 12px 3px;
}
.herdList { padding: 0 12px; display:flex; flex-wrap:wrap; gap:4px; }
.herdSlot {
  display:flex; gap:6px; align-items:baseline; max-width:100%;
  border:1px solid var(--edge); border-radius:4px; padding:1px 6px;
  font-size:11px;
}
/* Занятый слот — под частью, свободный — в резерве. Различие видно сразу. */
.herdSlot.busy { border-color:var(--accent); }
.herdSlot.idle { border-style:dashed; color:var(--dim); }
.hsRef { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:230px; }
/* Хвост аккаунта приглушён: он нужен, чтобы различать слоты одного шлюза,
   но важнее остальных сведений в строке не должен быть. */
.hsKey { color:var(--dim); font-family:var(--mono, monospace); font-size:10px; }
.hsOwner { color:var(--muted); white-space:nowrap; }

/* Панель субагентов: карточка на часть, след разворачивается по клику. */
.subsBox { margin: 0 0 8px; }
.subsBox:empty { display: none; }
.subCard {
  border:1px solid var(--edge); border-left:3px solid var(--accent);
  border-radius:var(--radius); background:var(--panel);
  padding:6px 10px; margin-bottom:6px;
}
.subCard.ok { border-left-color: var(--ok); }
.subCard.bad { border-left-color: var(--bad); }
/* Часть ждёт свободного аккаунта: она не упала, но и не идёт. */
.subCard.wait { border-left-color: var(--warn); opacity:.75; }
.subHead { display:flex; align-items:center; gap:8px; cursor:pointer; }
.subDot {
  width:7px; height:7px; border-radius:50%;
  background:var(--accent); flex:none;
}
.subCard.ok .subDot { background: var(--ok); }
.subCard.bad .subDot { background: var(--bad); }
/* Работающая часть мигает: иначе не видно, что она идёт, а не зависла. */
.subDot { animation: subPulse 1.4s ease-in-out infinite; }
.subCard.ok .subDot, .subCard.bad .subDot { animation: none; }
@keyframes subPulse { 0%,100% { opacity:1 } 50% { opacity:.35 } }
.subName { font-size:12.5px; font-weight:600; white-space:nowrap; }
.subTitle { font-size:12.5px; color:var(--muted); overflow:hidden;
            text-overflow:ellipsis; white-space:nowrap; }
.subModel {
  font-size:11px; color:var(--accent); border:1px solid var(--edge);
  border-radius:4px; padding:0 5px; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; max-width:190px;
}
.subStat { margin-left:auto; white-space:nowrap; }
.subMore { color:var(--dim); white-space:nowrap; }
.subWhy { color:var(--muted); margin-top:3px; }
.subFiles { margin-top:1px; }
.subTrail {
  margin-top:7px; padding-top:7px; border-top:1px solid var(--edge);
  max-height:420px; overflow:auto;
}
.subTrail[hidden] { display:none; }
.trailRow { margin-bottom:8px; }
.trailHead { font-size:11.5px; font-weight:600; color:var(--muted); }
.trailMsg { font-size:12px; white-space:pre-wrap; word-break:break-word; }
.trailPre {
  font-size:11.5px; white-space:pre-wrap; word-break:break-word;
  background:var(--bg); border:1px solid var(--edge); border-radius:5px;
  padding:5px 7px; margin:3px 0; max-height:220px; overflow:auto;
}
.trailMore summary { font-size:11.5px; color:var(--accent); cursor:pointer; }
.trailBad { font-size:11.5px; color:var(--bad); }
.trailEmpty { font-size:11.5px; color:var(--dim); }
/* Все части отработали — панель сворачивается, но остаётся доступной. */
.subsBox.done .subTrail { display:none; }

/* Разборка режима — под кнопкой режима, а не в настройках. */
#autoNote { margin: 0 2px 6px; min-height: 15px; }

/* Настройки субагентов и разведки — видны только когда включены. */
.subBox {
  border:1px solid var(--edge); border-radius:var(--radius);
  background:var(--panel); margin-bottom:6px; padding:8px 11px;
}
.subRow { display:flex; align-items:center; gap:10px; margin-bottom:5px; }
.srName { font-size:12.5px; }
.subHint { color:var(--muted); font-size:11.5px; }
.subWarn { color:var(--dim); font-size:11px; margin-top:5px; }

.mpMode {
  display:flex; align-items:center; gap:9px; padding:9px 11px;
  border-bottom:1px solid var(--edge); font-size:12.5px;
  cursor:pointer;
}
.mpMode:hover { background:color-mix(in srgb,var(--accent) 8%,transparent); }
.mpHead {
  display:flex; align-items:center; padding:7px 11px 4px; gap:8px;
}
.mpSearch { padding:0 11px 6px; }
.mpSearch input { width:100%; }

.mpList { max-height:250px; overflow:auto; border-top:1px solid var(--edge); }
.mpRow {
  display:flex; align-items:center; gap:8px; padding:7px 11px;
  cursor:pointer; border-left:2px solid transparent;
}
.mpRow:hover { background:color-mix(in srgb,var(--accent) 8%,transparent); }
.mpRow.on {
  background:color-mix(in srgb,var(--accent) 12%,transparent);
  border-left-color:var(--accent);
}
.mpRow .nm {
  flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.mpRow .radio { color:var(--dim); font-size:11px; width:10px; flex-shrink:0; }
.mpRow.on .radio { color:var(--accent); }

tr.on { background:color-mix(in srgb,var(--accent) 10%,transparent); }

.autoBox {
  margin:10px 12px 8px; padding:9px 11px;
  border:1px solid var(--edge); border-radius:var(--radius);
  background:var(--panel2);
}
.autoRow { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }

/* Мощность в аккаунтах: точка на ключ, крестик — выбит по лимиту. */
.klist { margin-top:6px; }
.krow {
  display:flex; align-items:center; gap:9px; padding:3px 0;
  font-size:12px;
}
.kgw { min-width:96px; color:var(--muted); }
.kmarks { flex:1; display:flex; flex-wrap:wrap; gap:2px; align-items:center; }
.kmark {
  color:var(--ok); font-size:13px; line-height:1;
  cursor:help;
}
.kmark.off { color:var(--warn); }
/* Ещё не использованный ключ — не «выбитый», просто пока без запросов. */
.kmark.idle { color:var(--dim); }
/* Аккаунт упирается в лимит минуты. Предупреждение, а не отказ: работы он
   не потерял, но новую часть ему выдавать уже нельзя. */
.kmark.tight { color:var(--accent); font-weight:700; }
/* Подпись лимита у шлюза. Без неё четыре метки подряд читаются как одна:
   метки одинаковые, и расстояние между ними ничего не сообщает. */
.krpm {
  color:var(--dim); font-size:10.5px; white-space:nowrap;
  border:1px solid var(--edge); border-radius:4px; padding:0 4px;
}
.kfree {
  color:var(--dim); font-family:var(--mono); font-size:11px;
  font-variant-numeric:tabular-nums;
}
button.busy { opacity:.6; cursor:progress; }

/* Кольцевой спиннер: вращающаяся дуга с градиентом */
.ring {
  width:15px; height:15px; border-radius:50%; flex-shrink:0;
  border:2px solid var(--edge); border-top-color:var(--accent);
  animation:ring-rot .8s linear infinite;
}
.ring.big { width:26px; height:26px; border-width:3px; }
@keyframes ring-rot { to { transform:rotate(360deg); } }

/* Точечные прыжки — для «думает» вместо кольца */
.dots { display:inline-flex; gap:3px; align-items:center; }
.dots i {
  width:4px; height:4px; border-radius:50%; background:var(--muted);
  animation:dot-b 1.15s ease-in-out infinite;
}
.dots i:nth-child(2) { animation-delay:.16s; }
.dots i:nth-child(3) { animation-delay:.32s; }
@keyframes dot-b {
  0%,60%,100% { transform:translateY(0); opacity:.45; }
  30% { transform:translateY(-4px); opacity:1; }
}

/* Полоса прогресса (ld-progress-bar): градиент + бегущий блик.
   Ширину задаёт inline-стиль, анимация только двигает блик и градиент. */
.barTrack {
  height:10px; background:var(--panel2); border-radius:999px; overflow:hidden;
  border:1px solid var(--edge);
}
.barFill {
  height:100%; width:40%; border-radius:999px;
  background:linear-gradient(90deg,var(--accent),
    color-mix(in srgb,var(--accent) 55%,var(--info)),var(--accent));
  background-size:200% 100%; position:relative;
  animation:bar-shine 1.5s linear infinite;
  transition:width .3s ease;
}
.barFill::after {
  content:''; position:absolute; inset:0;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.67),transparent);
  transform:translateX(-100%); animation:bar-sweep 1.5s linear infinite;
}
@keyframes bar-shine { to { background-position:200% 0; } }
@keyframes bar-sweep { to { transform:translateX(100%); } }

/* Полоса в полоска (pg-striped) — для долгих операций */
.barStripes { height:14px; background:var(--panel2); border-radius:999px;
  overflow:hidden; border:1px solid var(--edge); }
.barStripes i {
  display:block; height:100%; width:100%; border-radius:999px;
  background-color:var(--ok);
  background-image:linear-gradient(45deg,rgba(255,255,255,.2) 25%,transparent 25%,
    transparent 50%,rgba(255,255,255,.2) 50%,rgba(255,255,255,.2) 75%,
    transparent 75%,transparent);
  background-size:20px 20px; animation:stripes .6s linear infinite;
}
@keyframes stripes { to { background-position:20px 0; } }

/* Мерцающий текст (txt-shimmer): блик проходит по надписи */
.shimmer {
  background:linear-gradient(90deg,var(--dim) 0%,var(--dim) 40%,var(--text) 50%,
    var(--dim) 60%,var(--dim) 100%);
  background-size:200% auto; -webkit-background-clip:text; background-clip:text;
  color:transparent; animation:shimmer 2.5s linear infinite;
}
@keyframes shimmer { to { background-position:-200% center; } }

/* Бейдж статуса (tg-status-badge) с пульсирующей точкой */
.sbadge {
  display:inline-flex; align-items:center; gap:6px; padding:4px 11px;
  border-radius:20px; font-size:11.5px; font-weight:600;
  background:var(--panel2); border:1px solid var(--edge); color:var(--muted);
}
.sbadge i { width:8px; height:8px; border-radius:50%; background:var(--muted); flex-shrink:0; }
.sbadge.on {
  background:color-mix(in srgb,var(--ok) 9%,var(--panel));
  color:color-mix(in srgb,var(--ok) 80%,var(--text));
}
.sbadge.on i { background:var(--ok); animation:badge-pulse 1.8s infinite; }
.sbadge.warn {
  background:color-mix(in srgb,var(--warn) 9%,var(--panel));
  color:color-mix(in srgb,var(--warn) 80%,var(--text));
}
.sbadge.warn i { background:var(--warn); }
@keyframes badge-pulse {
  0% { box-shadow:0 0 0 0 color-mix(in srgb,var(--ok) 50%,transparent); }
  70% { box-shadow:0 0 0 8px transparent; }
  100% { box-shadow:0 0 0 0 transparent; }
}

/* Переключатель iOS (tg-ios) */
.isw { display:inline-block; width:40px; height:23px; border-radius:16px;
  background:var(--edge); position:relative; cursor:pointer; vertical-align:middle;
  transition:background .3s ease; flex-shrink:0; }
.isw::after {
  content:''; position:absolute; top:2px; left:2px; width:19px; height:19px;
  border-radius:50%; background:#fff; box-shadow:0 2px 4px rgba(0,0,0,.19);
  transition:transform .3s cubic-bezier(.4,1.4,.6,1);
}
.isw.on { background:var(--accent); }
.isw.on::after { transform:translateX(17px); }

/* Кнопка со сдвигом иконки (btn-icon-swap): текст и стрелка расходятся */
.swapBtn { overflow:hidden; }
.swapBtn .sb-tx { transition:transform .35s cubic-bezier(.5,0,.2,1); }
.swapBtn .sb-ic { display:inline-block; transition:transform .35s cubic-bezier(.5,0,.2,1); }
.swapBtn:hover .sb-tx { transform:translateX(-2px); }
.swapBtn:hover .sb-ic { transform:translateX(5px); }

/* Поле поиска (in-search-icon): круглая рамка, иконка растёт при фокусе */
.searchWrap {
  display:flex; align-items:center; gap:8px; padding:0 12px;
  background:var(--panel2); border:2px solid var(--edge); border-radius:30px;
  transition:border-color .25s ease, box-shadow .25s ease;
}
.searchWrap .sw-ic {
  color:var(--dim); display:flex; flex-shrink:0;
  transition:color .25s ease, transform .25s ease;
}
.searchWrap input {
  flex:1; min-width:0; padding:8px 0; font-size:13px; background:transparent;
  border:none; outline:none;
}
.searchWrap input:focus { box-shadow:none; }
.searchWrap:focus-within {
  border-color:var(--accent);
  box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 13%,transparent);
}
.searchWrap:focus-within .sw-ic { color:var(--accent); transform:scale(1.1); }

/* Карточка с мягким свечением (card-glow-border) */
.glowCard {
  border:1px solid var(--edge); border-radius:calc(var(--radius) + 6px);
  background:var(--panel2); padding:13px 14px;
  box-shadow:0 0 12px -10px var(--accent);
  transition:box-shadow .4s ease, border-color .4s ease, transform .3s ease;
}
.glowCard:hover {
  border-color:var(--accent);
  box-shadow:0 0 8px -5px var(--accent), 0 0 24px -14px var(--accent);
  transform:translateY(-2px);
}

/* ---------- каркас ---------- */
#app { display:flex; flex-direction:column; height:100vh; }
#top {
  display:flex; align-items:center; gap:10px; padding:0 12px; height:44px;
  border-bottom:1px solid var(--edge); background:var(--panel); flex:0 0 44px;
}
#brand { font-weight:600; letter-spacing:-.2px; display:flex; align-items:center; gap:7px; }
#brand .dot { width:7px; height:7px; border-radius:50%; background:var(--bad); }
#brand .dot.on { background:var(--ok); }
#top .sep { width:1px; height:20px; background:var(--edge); }
#topinfo { color:var(--muted); font-size:12px; overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap; }
#topinfo b { color:var(--text); font-weight:500; }

#main { flex:1; display:flex; min-height:0; }
.pane { display:flex; flex-direction:column; min-width:0; min-height:0; background:var(--panel); }
#left { flex:0 0 var(--lw,300px); border-right:1px solid var(--edge); }
#center { flex:1 1 auto; background:var(--bg); }
#right { flex:0 0 var(--rw,380px); border-left:1px solid var(--edge); }

.grip { flex:0 0 5px; cursor:col-resize; background:transparent; position:relative; }
.grip::after {
  content:''; position:absolute; inset:0 2px; background:var(--edge);
  transition:background .12s;
}
.grip:hover::after, .grip.drag::after { background:var(--accent); }
body.resizing { cursor:col-resize; user-select:none; }
body.resizing iframe { pointer-events:none; }

.phead {
  display:flex; align-items:center; gap:6px; padding:0 10px; height:36px;
  border-bottom:1px solid var(--edge); flex:0 0 36px; font-size:12px;
  color:var(--muted); text-transform:uppercase; letter-spacing:.5px; font-weight:600;
}
.phead .spacer { flex:1; }
.ptabs { display:flex; gap:2px; padding:6px 8px 0; flex:0 0 auto; }
.ptab {
  padding:5px 10px; font-size:12px; color:var(--muted); border-radius:6px 6px 0 0;
  border:1px solid transparent; border-bottom:0;
}
.ptab.on { background:var(--bg); color:var(--text); border-color:var(--edge); }
.pbody { flex:1; overflow:auto; min-height:0; }
.psec { display:none; } .psec.on { display:block; }

/* ---------- модели ---------- */
.mgroup { padding:8px 10px; border-bottom:1px solid var(--edge); }
.mgroup h4 { font-size:11px; color:var(--dim); text-transform:uppercase;
  letter-spacing:.6px; margin-bottom:6px; font-weight:600; }
.kv { display:grid; grid-template-columns:auto 1fr; gap:3px 8px; font-size:12px; }
.kv dt { color:var(--muted); }
.kv dd { font-family:var(--mono); font-size:11.5px; word-break:break-all;
  cursor:pointer; color:var(--text); }
.kv dd:hover { color:var(--accent); }
.kv dd.copy::after { content:' ⧉'; color:var(--dim); font-size:10px; }

.chip { display:inline-block; padding:1px 6px; border-radius:4px; font-size:10.5px;
  font-weight:600; letter-spacing:.2px; }
/* Цвета бейджей выводятся из токенов статуса: в светлой теме тёмный фон
   с ярким текстом читался бы хуже, чем наоборот. */
.chip.ok,.chip.good,.chip.done {
  background:color-mix(in srgb,var(--ok) 14%,var(--panel));
  color:color-mix(in srgb,var(--ok) 82%,var(--text)); }
.chip.warn,.chip.slow,.chip.usable,.chip.asking {
  background:color-mix(in srgb,var(--warn) 14%,var(--panel));
  color:color-mix(in srgb,var(--warn) 82%,var(--text)); }
.chip.info,.chip.limited,.chip.empty,.chip.queued {
  background:color-mix(in srgb,var(--info) 14%,var(--panel));
  color:color-mix(in srgb,var(--info) 82%,var(--text)); }
.chip.bad,.chip.blocked,.chip.down,.chip.poor,.chip.failed {
  background:color-mix(in srgb,var(--bad) 14%,var(--panel));
  color:color-mix(in srgb,var(--bad) 82%,var(--text)); }

/* ---------- доступность из региона ---------- */
.ru {
  font-size:10px; padding:1px 5px; border-radius:4px; flex-shrink:0;
  font-weight:600; letter-spacing:.02em; white-space:nowrap;
}
.ru-ok      { background:color-mix(in srgb,var(--ok) 16%,var(--panel));
              color:color-mix(in srgb,var(--ok) 84%,var(--text)); }
.ru-vpn     { background:color-mix(in srgb,var(--warn) 16%,var(--panel));
              color:color-mix(in srgb,var(--warn) 84%,var(--text)); }
.ru-blocked { background:color-mix(in srgb,var(--bad) 16%,var(--panel));
              color:color-mix(in srgb,var(--bad) 84%,var(--text)); }
.ru-unknown { background:var(--panel2); color:var(--muted); }
/* Переключатель тем: точки вместо списка — пять вариантов не помещаются
   в выпадающий список на верхней панели, а помещаются в ряд точек. */
.themePick {
  display:flex; align-items:center; gap:3px; padding:2px 4px;
  border:1px solid var(--edge); border-radius:99px; background:var(--panel2);
}
.themeDot {
  width:15px; height:15px; border-radius:50%; border:1px solid var(--edge);
  cursor:pointer; padding:0; position:relative; flex-shrink:0;
  transition:transform .12s ease,box-shadow .15s ease;
}
.themeDot:hover { transform:scale(1.14); }
.themeDot.on {
  box-shadow:0 0 0 2px var(--panel2),0 0 0 3px var(--accent);
}
.themeDot[data-t="dark"]  { background:linear-gradient(135deg,#3b82f6 0 50%,#0d1014 50%); }
.themeDot[data-t="black"] { background:linear-gradient(135deg,#4f8ef7 0 50%,#000 50%); }
.themeDot[data-t="light"] { background:linear-gradient(135deg,#2563eb 0 50%,#f7f8fa 50%); }
.themeDot[data-t="blue"]  { background:linear-gradient(135deg,#38bdf8 0 50%,#0a1220 50%); }
.themeDot[data-t="gray"]  { background:linear-gradient(135deg,#c9c9c9 0 50%,#141414 50%); }

/* ---------- панель замера доступности ---------- */
.geoBox {
  margin:0 0 8px; padding:9px 10px; border:1px solid var(--edge);
  border-radius:8px; background:var(--panel2);
}
.geoStep { font-size:12px; margin-bottom:6px; color:var(--muted); }
.geoStep b { color:var(--text); }
.geoStat {
  display:flex; gap:10px; font-size:11px; color:var(--muted); margin-bottom:7px;
  font-variant-numeric:tabular-nums;
}
.geoStat .dim {
  margin-left:auto; font-family:var(--mono); font-size:10.5px;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:45%;
}
.geoSum { display:flex; gap:5px; margin-bottom:8px; }
.geoSteps { display:flex; flex-direction:column; gap:5px; }
.geoStepRow {
  display:flex; align-items:center; gap:8px; padding:6px 8px;
  border:1px solid var(--edge); border-radius:7px; font-size:11.5px;
  color:var(--muted);
}
.geoStepRow.now {
  border-color:color-mix(in srgb,var(--accent) 40%,var(--edge));
  background:color-mix(in srgb,var(--accent) 8%,var(--panel2));
}
.geoStepRow.done { color:var(--dim); }
.geoStepRow .n {
  width:17px; height:17px; flex-shrink:0; border-radius:50%;
  display:flex; align-items:center; justify-content:center; font-size:10px;
  background:var(--panel2); color:var(--muted); border:1px solid var(--edge);
}
.geoStepRow.now .n { background:var(--accent); color:var(--accent-text); font-weight:700; }
.geoStepRow.done .n {
  background:color-mix(in srgb,var(--ok) 18%,var(--panel));
  color:color-mix(in srgb,var(--ok) 84%,var(--text));
}
.geoStepRow .tx { flex:1; line-height:1.45; }
.geoStepRow .tx b { color:var(--text); }
.geoHint {
  margin-top:7px; font-size:10.5px; color:var(--muted); line-height:1.5;
  padding-top:7px; border-top:1px solid var(--edge);
}
.geoLog {
  margin-top:6px; font-family:var(--mono); font-size:10px; color:var(--dim);
  line-height:1.6; max-height:76px; overflow-y:auto;
}
.chip.mute,.chip.unknown,.chip.skipped,.chip.running,.chip.paused,.chip.cancelled,
.chip.note { background:var(--panel2); color:var(--muted); }

/* Кнопки: заливка акцентом, при наведении светлее — считается через
   color-mix от токена, поэтому работает в любой теме. */
.btn {
  padding:5px 11px; border-radius:6px; background:var(--panel2);
  border:1px solid var(--edge); font-size:12px; color:var(--text);
  transition:background .15s ease,border-color .15s ease,transform .12s ease;
}
.btn:hover {
  border-color:color-mix(in srgb,var(--accent) 45%,var(--edge));
  background:color-mix(in srgb,var(--accent) 10%,var(--panel2));
}
.btn:active { transform:translateY(1px); }
.btn:disabled { opacity:.45; cursor:not-allowed; transform:none; }
.btn.pri {
  background:var(--accent); border-color:var(--accent);
  color:var(--accent-text); font-weight:500;
}
.btn.pri:hover { background:color-mix(in srgb,var(--accent) 85%,#fff); }
.btn.sm { padding:3px 8px; font-size:11px; }
.btn.danger {
  background:color-mix(in srgb,var(--bad) 16%,var(--panel));
  border-color:color-mix(in srgb,var(--bad) 40%,var(--edge));
  color:color-mix(in srgb,var(--bad) 82%,var(--text));
}

.row { display:flex; gap:6px; align-items:center; padding:8px 10px; flex-wrap:wrap; }
.row.tight { padding:6px 10px; }
.field { margin:0 10px 8px; }
.field label { display:block; font-size:11px; color:var(--muted); margin-bottom:3px; }
.field select,.field input,.field textarea { width:100%; }

pre {
  background:var(--bg); border:1px solid var(--edge); border-radius:7px; padding:10px;
  overflow:auto; font-family:var(--mono); font-size:11.5px; line-height:1.5;
  white-space:pre-wrap; word-break:break-word; max-height:340px; margin:0 10px 10px;
}
code.inl { font-family:var(--mono); font-size:11.5px; background:var(--panel2);
  padding:1px 5px; border-radius:4px; }

.muted { color:var(--muted); } .dim { color:var(--dim); }

  /* Таблица всех моделей в отладчике. Цвета — только из токенов темы:
     иначе блок выглядел бы чужеродно в светлой и серой темах. */
  .modelsTable { display:flex; flex-direction:column; gap:4px; margin-top:6px; }
  .modelsRow {
    display:grid; grid-template-columns:minmax(120px,1fr) auto;
    gap:2px 10px; padding:6px 8px; border:1px solid var(--line);
    border-radius:var(--radius); background:var(--panel2);
  }
  .modelsRow .mini { grid-column:1 / -1; white-space:pre-wrap;
    word-break:break-word; }
  .modelsName {
    font-family:var(--mono, ui-monospace, Consolas, monospace);
    font-size:11.5px; color:var(--text); overflow:hidden;
    text-overflow:ellipsis; white-space:nowrap;
  }
  .modelsName:hover { color:var(--accent); }
.mini { font-size:11.5px; }
.note { background:color-mix(in srgb,var(--info) 10%,var(--panel));
  border-left:2px solid var(--info); padding:8px 10px;
  margin:0 10px 10px; font-size:12px; border-radius:0 6px 6px 0; }
.warnbox { background:color-mix(in srgb,var(--warn) 10%,var(--panel));
  border-left:2px solid var(--warn); padding:8px 10px;
  margin:0 10px 10px; font-size:12px; border-radius:0 6px 6px 0; }

/* ---------- центр ---------- */
#msgs { flex:1; overflow:auto; padding:14px 16px; }
.msg { margin-bottom:14px; max-width:78ch; }
.msg .who { font-size:11px; color:var(--dim); margin-bottom:3px;
  display:flex; gap:7px; align-items:center; }
.msg .body { white-space:pre-wrap; word-break:break-word; }
.msg.user .body {
  background:color-mix(in srgb,var(--accent) 14%,var(--panel));
  padding:9px 12px; border-radius:9px;
  border:1px solid color-mix(in srgb,var(--accent) 30%,var(--edge));
}
.msg.sys .body { color:var(--muted); font-size:12.5px; font-style:italic; }
.msg.tool .body { font-family:var(--mono); font-size:11.5px; }
.toolline { display:flex; gap:8px; align-items:baseline; padding:4px 8px;
  background:var(--panel); border-radius:6px; margin:3px 0; font-size:12px; }
.toolline .nm { font-family:var(--mono); color:var(--info); flex:0 0 auto; }
.toolline .tx { color:var(--muted); word-break:break-word; }
.toolline.bad .nm { color:var(--bad); }
/* Чем занята часть работы прямо сейчас. Отличается от `.subStat`: там счёт,
   здесь — конкретное дело, и по нему видно, какая часть зависла. */
.subNow { color:var(--muted); font-size:11.5px; margin-top:2px;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.subNow:not(:empty) { color:var(--info); }
/* Полоса хода задачи: видно, что агент делает сейчас, сколько шагов и
   токенов потрачено и сколько ещё есть. Без неё длинная задача выглядит
   как зависшая: последнее, что видно, — давний вызов инструмента.
   Показывается только во время работы, в покое она занимает место и
   сообщает ноль, то есть ничего. */
.progBar { display:flex; flex-wrap:wrap; align-items:center; gap:8px;
  padding:6px 10px; border-bottom:1px solid var(--line);
  font-size:12px; background:var(--panel); }
.progBar[hidden] { display:none; }
.progNow { font-weight:600; max-width:52%; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap; }
.progTrack { flex:1 1 90px; min-width:70px; height:4px; border-radius:3px;
  background:var(--line); overflow:hidden; }
.progFill { height:100%; background:var(--accent); border-radius:3px;
  transition:width .25s ease; }
.progFill.warn { background:var(--warn); }
.progNum { color:var(--muted); font-family:var(--mono); font-size:11px;
  white-space:nowrap; }
.verify { background:color-mix(in srgb,var(--info) 10%,var(--panel)); border-radius:6px;
  padding:4px 8px; margin:3px 0; font-size:12px; }
.verify.bad { background:color-mix(in srgb,var(--bad) 12%,var(--panel)); }

/* Созданные файлы: результат работы должен открываться в один клик,
   иначе после задачи остаётся только текст со списком имён файлов. */
.arts { border:1px solid var(--ok); border-radius:8px; margin:8px 0;
  overflow:hidden; background:var(--panel); }
.artsHead { background:color-mix(in srgb,var(--ok) 14%,var(--panel));
  padding:5px 10px; font-size:12px; color:var(--ok); font-weight:600; }
.artRow { display:flex; align-items:center; gap:8px; padding:5px 10px;
  border-top:1px solid var(--edge); font-size:12.5px; }
.artRow:first-child { border-top:none; }
.artIcon { color:var(--dim); flex:0 0 auto; width:10px; }
.artName { color:var(--info); text-decoration:none; font-family:var(--mono);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.artName:hover { text-decoration:underline; }
.artGo { margin-left:auto; flex:0 0 auto; color:var(--ok); text-decoration:none;
  font-size:11.5px; border:1px solid var(--ok); border-radius:5px;
  padding:2px 7px; }
.artGo:hover { background:color-mix(in srgb,var(--ok) 16%,var(--panel)); }
.artHint { margin-left:auto; flex:0 0 auto; color:var(--dim); font-size:11px;
  font-style:italic; }

/* Меню правого клика по файлу в дереве. */
.ctxmenu {
  position:fixed; z-index:80; min-width:190px; padding:4px;
  background:var(--panel); border:1px solid var(--edge);
  border-radius:var(--radius); box-shadow:0 8px 26px rgba(0,0,0,.35);
}
.ctxitem { padding:5px 10px; border-radius:5px; font-size:12.5px; cursor:pointer; }
.ctxitem:hover { background:var(--panel2); color:var(--accent); }

/* Свой диалог: родной prompt() подавляется во встроенных браузерах, и
   кнопки, на которых он стоял, выглядели неработающими. */
.dlgWrap {
  position:fixed; inset:0; z-index:90; display:flex; align-items:center;
  justify-content:center; background:rgba(0,0,0,.45); padding:20px;
}
.dlgWrap[hidden] { display:none; }
.dlg {
  width:min(520px,100%); background:var(--panel); border:1px solid var(--edge);
  border-radius:12px; padding:16px; box-shadow:0 16px 48px rgba(0,0,0,.45);
}
.dlgTitle { font-size:14px; font-weight:600; margin-bottom:8px; }
.dlgText { color:var(--muted); font-size:12.5px; margin-bottom:10px;
  white-space:pre-wrap; }
.dlgText:empty { display:none; }
#dlgExtra:empty { display:none; }
#dlgInput {
  width:100%; margin-top:4px; padding:8px 10px; font-size:13px;
  font-family:var(--mono); background:var(--panel2); color:var(--text);
  border:1px solid var(--edge); border-radius:7px;
}
#dlgInput:focus-visible { outline:2px solid var(--accent); outline-offset:-1px; }
.dlgFoot { display:flex; gap:8px; justify-content:flex-end; margin-top:14px; }

#composer { flex:0 0 auto; border-top:1px solid var(--edge); background:var(--panel);
  padding:10px 12px; }
#attach { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:7px; }
.att { display:flex; align-items:center; gap:5px; background:var(--panel2);
  border:1px solid var(--edge); border-radius:6px; padding:3px 8px; font-size:11.5px; }
.att img { width:26px; height:26px; object-fit:cover; border-radius:3px; }
.att .x { color:var(--dim); cursor:pointer; } .att .x:hover { color:var(--bad); }
#cbox { min-height:64px; max-height:200px; }
#cfoot { display:flex; gap:8px; align-items:center; margin-top:8px; flex-wrap:wrap; }
#cfoot .spacer { flex:1; }

/* ---------- файлы ---------- */
#ftree { padding:4px 0; }
.fdir { padding:4px 12px; color:var(--muted); font-size:11.5px;
  font-family:var(--mono); border-bottom:1px solid var(--edge); background:var(--panel2);
  position:sticky; top:0; }
.fitem { display:flex; gap:7px; align-items:center; padding:3px 12px; font-size:12px;
  cursor:pointer; }
.fitem:hover { background:var(--panel2); }
.fitem.on { background:var(--accent-dim); }
.fitem .ic { color:var(--dim); flex:0 0 12px; font-size:10px; }
.fitem .nm { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.fitem .sz { color:var(--dim); font-size:10.5px; }
#fview { flex:1; overflow:auto; }
#fview pre { margin:0; border:0; border-radius:0; background:var(--bg);
  max-height:none; min-height:100%; padding:12px 14px; font-size:12px; }

table { width:100%; border-collapse:collapse; font-size:12px; }
th,td { text-align:left; padding:5px 10px; border-bottom:1px solid var(--edge); }
th { color:var(--dim); font-weight:600; font-size:11px; text-transform:uppercase;
  letter-spacing:.4px; position:sticky; top:0; background:var(--panel); }

.empty { padding:30px 16px; text-align:center; color:var(--dim); font-size:12.5px; }

/* ---------- панель воркспейса ---------- */
.spaceNow {
  margin:0 0 10px; padding:11px 12px; border:1px solid var(--edge);
  border-radius:9px; background:var(--panel2);
}
.spaceNow .t {
  font-weight:600; font-size:13.5px; display:flex; align-items:center; gap:7px;
  margin-bottom:5px;
}
.spaceNow .t .ic { color:var(--accent); font-size:14px; }
.spaceNow .p {
  font-family:var(--mono); font-size:11px; color:var(--dim);
  word-break:break-all; line-height:1.5;
}
.spaceNow .s {
  margin-top:8px; padding-top:8px; border-top:1px solid var(--edge);
  font-size:12px; color:var(--muted); display:flex; align-items:center; gap:6px;
}
.spaceNow .s b { color:var(--text); font-weight:600; }
.sess {
  display:flex; align-items:center; gap:8px; padding:7px 10px; cursor:pointer;
  border-radius:7px; border:1px solid transparent;
}
.sess:hover { background:var(--panel2); }
.sess.on {
  background:color-mix(in srgb,var(--accent) 12%,var(--panel));
  border-color:color-mix(in srgb,var(--accent) 35%,var(--edge));
}
.sess .nm { flex:1; font-size:12.5px; min-width:0; }
.sess .nm div {
  font-size:10.5px; color:var(--muted); white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; margin-top:1px;
}
.sess .x {
  opacity:0; border:none; background:none; color:var(--muted); cursor:pointer;
  font-size:13px; padding:2px 5px; border-radius:4px;
}
.sess:hover .x { opacity:1; }
.sess .x:hover {
  color:var(--bad); background:color-mix(in srgb,var(--bad) 15%,var(--panel));
}
.sess .badge {
  font-size:10px; padding:1px 5px; border-radius:4px; background:var(--panel2);
  color:var(--muted); flex-shrink:0;
}

/* ---------- диалог разрешения ---------- */
#modal {
  position:fixed; inset:0; background:rgba(0,0,0,.62); display:none;
  align-items:center; justify-content:center; z-index:100; padding:20px;
  backdrop-filter:blur(2px);
}
#modal.on { display:flex; }
#modalBox {
  background:var(--panel); border:1px solid var(--edge); border-radius:12px;
  width:min(560px,100%); box-shadow:var(--shadow); overflow:hidden;
}
#modalBox .mh {
  padding:14px 18px; border-bottom:1px solid var(--edge); font-weight:600;
  display:flex; gap:9px; align-items:center; font-size:14px;
}
#modalBox .mh .ic { font-size:17px; }
#modalBox .mb { padding:16px 18px; font-size:13px; }
#modalBox .mb .q { margin-bottom:14px; white-space:pre-wrap; color:var(--text);
  line-height:1.6; }
#modalBox .mp {
  font-family:var(--mono); font-size:11.5px; background:var(--bg);
  border:1px solid var(--edge); border-radius:7px; padding:9px 11px;
  margin-bottom:14px; word-break:break-all;
  color:color-mix(in srgb,var(--info) 80%,var(--text));
}
#modalBox .mf {
  padding:12px 18px; border-top:1px solid var(--edge); display:flex; gap:8px;
  justify-content:flex-end; background:var(--panel2); flex-wrap:wrap;
}
#modalBox .mf .grow { flex:1; }
#modalBox .hint { font-size:11.5px; color:var(--muted); margin-top:-6px; margin-bottom:12px; }
#bell {
  position:fixed; right:14px; bottom:14px;
  background:color-mix(in srgb,var(--warn) 16%,var(--panel));
  border:1px solid color-mix(in srgb,var(--warn) 42%,var(--edge));
  color:color-mix(in srgb,var(--warn) 84%,var(--text));
  padding:9px 15px; border-radius:9px; cursor:pointer; font-size:13px;
  display:none; box-shadow:var(--shadow); z-index:90;
}
#bell.on { display:block; animation:pulse 1.8s infinite; }
@keyframes pulse {
  0%,100% { box-shadow:var(--shadow); }
  50% { box-shadow:0 8px 26px -4px color-mix(in srgb,var(--warn) 45%,transparent); }
}
</style>
</head>
<body>
<div id="app">

<div id="top">
  <div id="brand"><span class="sbadge" id="liveBadge"><i></i><span id="liveTx">соединяюсь</span></span>zagent</div>
  <div class="sep"></div>
  <div id="topinfo">загрузка…</div>
  <div class="sep"></div>
  <select id="wsSel" style="max-width:200px" onchange="switchWs(this.value)"
          title="Воркспейс: папка, в которой работает агент"></select>
  <button class="btn sm" onclick="newSession()" title="Новая сессия в этом же воркспейсе"
          id="newSessBtn">новая</button>
  <div class="themePick" title="Оформление">
    <button class="themeDot" data-t="dark"  onclick="setTheme('dark')"  title="Тёмная"></button>
    <button class="themeDot" data-t="black" onclick="setTheme('black')" title="Чёрная"></button>
    <button class="themeDot" data-t="light" onclick="setTheme('light')" title="Светлая"></button>
    <button class="themeDot" data-t="blue"  onclick="setTheme('blue')"  title="Синяя"></button>
    <button class="themeDot" data-t="gray"  onclick="setTheme('gray')"  title="Серая"></button>
  </div>
  <div style="flex:1"></div>
  <button class="btn sm" onclick="api('/api/pause',{resume:S.paused}).then(refresh)"
          id="pauseBtn">пауза</button>
</div>

<div id="main">

<!-- ================= СЛЕВА ================= -->
<div class="pane" id="left">
  <div class="ptabs">
    <button class="ptab on" data-p="models" onclick="ltab('models')">Модели</button>
    <button class="ptab" data-p="access" onclick="ltab('access')">Доступ</button>
    <button class="ptab" data-p="settings" onclick="ltab('settings')">Настройки</button>
    <button class="ptab" data-p="space" onclick="ltab('space')">Папка и сессии</button>
    <button class="ptab" data-p="status" onclick="ltab('status')">Статус</button>
    <button class="ptab" data-p="queue" onclick="ltab('queue')">Очередь</button>
    <button class="ptab" data-p="local" onclick="ltab('local')">Локальные модели</button>
    <button class="ptab" data-p="guide" onclick="ltab('guide')">Гайды по API</button>
  </div>
  <div class="pbody">

    <!-- вкладка МОДЕЛИ

         Главное здесь — выбрать модель. Всё остальное (пинг, проверка
         адекватности, ключи шлюзов, доступность из РФ, инструкции для
         другого софта) спрятано в раскрывающиеся блоки: раньше оно лежало
         свёрху и вытесняло сам список моделей, который здесь и нужен. -->
    <div class="psec on" id="p-models">

      <!-- выбор режима и модели -->
      <div class="modePick">
        <div class="row tight">
          <span class="isw on" id="modeSw" title="auto — лучшая доступная"></span>
          <select id="modeSel" style="flex:1" onchange="setMode(this.value)">
            <option value="auto">auto — лучшая доступная</option>
            <option value="manual">ручной выбор модели</option>
          </select>
        </div>
        <div id="modeNote" class="modeNote"></div>
      </div>

      <div class="row tight">
        <div class="searchWrap" style="flex:1">
          <span class="sw-ic">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
                 stroke-width="2.5" stroke-linecap="round">
              <circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/>
            </svg>
          </span>
          <input id="modelFilter" placeholder="Фильтр по названию…" oninput="renderModels()">
        </div>
      </div>

      <div id="modelList"></div>

      <!-- спрятанные блоки -->
      <div class="fold">
        <button class="foldHead" onclick="fold(this)">
          <span class="foldIc">▸</span>
          <span>Доступность из России</span>
          <span class="dim mini" id="geoHint"></span>
        </button>
        <div class="foldBody" id="fGeo" hidden></div>
      </div>

      <div class="fold" data-open="1">
        <button class="foldHead" onclick="fold(this)">
          <span class="foldIc">▾</span>
          <span>Ключи и адреса шлюзов</span>
        </button>
        <div class="foldBody">
          <div class="hintBlock">
            Provider id, base URL и ключ — то, что нужно, чтобы подключить эти же
            шлюзы к другому софту. Для работы агента не требуется.
          </div>
          <div id="gwList"></div>
        </div>
      </div>

      <div class="fold" data-open="1">
        <button class="foldHead" onclick="fold(this)">
          <span class="foldIc">▾</span>
          <span>Подключить к другому софту</span>
        </button>
        <div class="foldBody">
          <select id="targetSel" style="width:100%;margin-bottom:7px"
                  onchange="loadGuide(this.value)">
            <option value="opencode">OpenCode</option>
            <option value="deepseek">DeepSeek Harness</option>
            <option value="codex">Codex CLI</option>
            <option value="zed">Zed</option>
            <option value="cline">Cline / Roo / Kilo</option>
          </select>
          <div id="guideBox"></div>
        </div>
      </div>
    </div>

    <!-- вкладка ДОСТУП -->
    <div class="psec" id="p-access">
      <div class="field">
        <label>Уровень доступа</label>
        <select id="accSel" onchange="cfg({access:+this.value})">
          <option value="1">1 — только чтение</option>
          <option value="2">2 — чтение и запись</option>
          <option value="3">3 — полный доступ</option>
        </select>
      </div>
      <div class="field">
        <label>Автономия</label>
        <select id="autoSel" onchange="cfg({autonomy:this.value})">
          <option value="yolo">yolo — решает сам</option>
          <option value="normal">normal — спрашивает перед рискованным</option>
          <option value="strict">strict — спрашивает перед каждой правкой</option>
          <option value="plan">plan — сначала план</option>
        </select>
      </div>
      <div class="field">
        <label>Помощь пользователя</label>
        <select id="escSel" onchange="cfg({escalation:this.value})">
          <option value="off">off — не просить</option>
          <option value="auto">auto — только когда иначе никак</option>
          <option value="on">on — при любом сомнении</option>
        </select>
      </div>
      <div class="field">
        <label>Максимум шагов</label>
        <input type="number" id="stepsIn" min="1" max="200"
               onchange="cfg({max_steps:+this.value})">
      </div>
      <div class="field">
        <label>Доступность из России</label>
        <select id="vpnSel" onchange="cfg({avoid_vpn:this.value==='avoid'})">
          <option value="off">не учитывать VPN</option>
          <option value="avoid">VPN выключен — сначала модели без VPN</option>
        </select>
      </div>
      <div class="note" id="vpnNote"></div>
      <div class="field">
        <label>Граница воркспейса</label>
        <select id="boundSel" onchange="cfg({soft_boundary:this.value==='soft'})">
          <option value="soft">мягкая — спрашивает (рекомендуется)</option>
          <option value="hard">жёсткая — выход невозможен</option>
        </select>
      </div>
      <div class="note" id="boundNote">
        <b>Мягкая граница:</b> если задача требует выхода за папку воркспейса,
        агент останавливается и спрашивает вас. Появится окно с путём и тремя
        кнопками: «Только сейчас», «Всегда разрешить», «Отклонить». Отказ
        агент получает как ошибку и пробует обойтись без этого пути.
        <br><br>
        <b>Жёсткая граница:</b> агент никогда не выйдет за пределы папки.
      </div>
      <div id="wsList"></div>
    </div>

    <!-- вкладка НАСТРОЙКИ

         Ключи и модели заводятся отсюда, а не правкой файлов руками: сервер
         пишет config/secrets.local.json, gateways.json и tiers.json и сам
         пересобирает каталог. Значения ключей в интерфейс не возвращаются —
         только имена полей и счётчики (build_settings). -->
    <div class="psec" id="p-settings">

      <div class="fold" data-open="1">
        <button class="foldHead" onclick="fold(this)">
          <span class="foldIc">▾</span>
          <span>Ключи шлюзов</span>
        </button>
        <div class="foldBody">
          <div class="hintBlock">
            Вставьте ключи: по одному в строке — можно сразу несколько аккаунтов,
            они пойдут в ротацию по кругу. Строки с запятыми тоже читаются.
            Значения остаются в config/secrets.local.json (в .git) и обратно
            в браузер не уходят.
          </div>

          <div class="field">
            <label>Шлюз</label>
            <select id="keyGw" onchange="renderKeySide()"></select>
          </div>
          <div class="field">
            <label id="keyInfo">данные шлюза</label>
          </div>
          <div id="keyExtra"></div>
          <div class="field">
            <label>Ключи (по одному в строке)</label>
            <textarea id="keyText" rows="4" spellcheck="false"
                      placeholder="gsk_…&#10;gsk_…&#10;gsk_…"></textarea>
          </div>
          <div class="row tight">
            <button class="btn sm pri" onclick="keysSend('add')">Добавить</button>
            <button class="btn sm" onclick="keysSend('replace')">Заменить всё</button>
            <button class="btn sm" onclick="keysSend('remove')">Удалить вставленные</button>
          </div>
          <div class="mini dim" id="keyMsg" style="padding:2px 10px 8px"></div>
        </div>
      </div>

      <!-- РЕЖИМ РАЗРАБОТЧИКА

           Переключатель, который виден пользователю, а не только автору.
           Что он делает и что не делает — написано прямо здесь, потому
           что режим с названием «разработка» у людей вызывает ожидание
           «агент начнёт сам себя править». Не начнёт: право править код
           выдаётся на одну задачу отдельно, намеренно. Здесь только
           диагностика установки — пути, счётчики, последняя ошибка. -->
      <div class="fold">
        <button class="foldHead" onclick="fold(this)">
          <span class="foldIc">▸</span>
          <span>Режим разработчика</span>
        </button>
        <div class="foldBody" hidden>
          <div class="hintBlock">
            Показывает диагностику: где лежат проект и база, сколько
            накопилось задач и событий, какая ошибка висит последней и
            какая версия Python подняла сервер. Значения ключей здесь
            не появляются никогда — только имена полей и счётчики.
            Переживает перезапуск сервера.
          </div>
          <div class="row tight">
            <button class="btn sm pri" id="devBtn" onclick="devToggle()">Включить</button>
            <button class="btn sm" onclick="devRefresh()">Обновить</button>
            <button class="btn sm" onclick="diagShow()">Журнал ошибк</button>
            <button class="btn sm" onclick="diagClear()">Очистить журнал</button>
            <span class="mini dim" id="devMsg"></span>
          </div>
          <div id="devBox" style="padding:6px 10px 4px" hidden></div>

          <!-- Все модели: статус и общий вопрос. Данные приходят с
               сервера, который сам ходит в мост на 8784. -->
          <div class="hintBlock">
            Статус каждой модели: «отвечает», «отказала», «на остывании»
            или «ещё не проверена», с временем последнего ответа и
            причиной отказа. Кнопка ниже отправляет один вопрос сразу
            всем моделям — они отвечают параллельно, ждать по очереди
            не нужно. Модели на остывании в опрос не идут: они и так
            известно не отвечают, но в таблице остаются со своей
            причиной.
          </div>
          <div class="row tight">
            <button class="btn sm pri" onclick="modelsStatus()">Статус всех моделей</button>
            <button class="btn sm" onclick="modelsAskAll()">Спросить всех</button>
            <span class="mini dim" id="modelsMsg"></span>
          </div>
          <div class="field">
            <label>Вопрос для всех моделей</label>
            <textarea id="modelsAsk" rows="2"
              placeholder="Ответь одним предложением: ты работаешь?">(текст)</textarea>
          </div>
          <div id="modelsBox" style="padding:4px 10px 8px" hidden></div>

          <div id="diagBox" style="padding:4px 10px 8px" hidden></div>
        </div>
      </div>

      <div class="fold">
        <button class="foldHead" onclick="fold(this)">
          <span class="foldIc">▸</span>
          <span>Модели</span>
        </button>
        <div class="foldBody" hidden>
          <div class="hintBlock">
            Свою модель добавляют сразу в два места: tiers.json — приоритет
            и заметка, free_models шлюза — каталог, без которого селектор её
            не увидит. 1 — лучшая, 5 — запасная.
          </div>
          <div class="field">
            <label>Шлюз</label>
            <select id="modGw" onchange="renderModelList()"></select>
          </div>
          <div class="field">
            <label>Идентификатор модели</label>
            <input id="modId" spellcheck="false" placeholder="gemini-3.8-flash-lite">
          </div>
          <div class="field">
            <label>Приоритет (тир)</label>
            <select id="modTier">
              <option value="1">1 — лучшая</option>
              <option value="2">2 — сильная</option>
              <option value="3" selected>3 — обычная</option>
              <option value="4">4 — запасная</option>
              <option value="5">5 — крайняя</option>
            </select>
          </div>
          <div class="field">
            <label>Заметка (необязательно)</label>
            <input id="modNote" spellcheck="false" placeholder="почему этот ранг">
          </div>
          <div class="row tight">
            <button class="btn sm pri" onclick="modelSend('add')">Добавить модель</button>
            <button class="btn sm" onclick="modelSend('remove')">Удалить модель</button>
          </div>
          <div class="mini dim" id="modMsg" style="padding:2px 10px 8px"></div>
          <div id="modList"></div>
        </div>
      </div>

      <div class="fold">
        <button class="foldHead" onclick="fold(this)">
          <span class="foldIc">▸</span>
          <span>Где брать ключи</span>
        </button>
        <div class="foldBody" hidden>
          <div class="hintBlock">
            Пошаговый гайд: где регистрироваться, где кнопка создания ключа,
            лимиты, таблица VPN и диагностика ошибок.
          </div>
          <div class="row tight">
            <button class="btn sm" onclick="ltab('guide')">Открыть «Гайды по API»</button>
          </div>
        </div>
      </div>
    </div>

    <!-- вкладка ПАПКА И СЕССИИ -->
    <div class="psec" id="p-space">
      <!-- Где мы сейчас. Это главный ответ на вопрос «что агент будет менять»,
           поэтому путь показан целиком, а не именем папки. -->
      <div class="spaceNow" id="spaceNow"></div>

      <div class="row tight">
        <button class="btn sm pri" style="flex:1" onclick="newSession()">
          новая сессия
        </button>
        <button class="btn sm" onclick="wsAdd()">выбрать папку</button>
      </div>
      <div class="note">
        <b>Сессия</b> — переписка внутри папки. «Новая сессия» оставляет ту же
        папку, но начинает историю с чистого листа: файлы, права и настройки те
        же, прошлая переписка остаётся в списке.
        <br><br>
        <b>«Выбрать папку»</b> — открыть папку на компьютере и работать в ней.
        Всё, что агент создаст, попадёт туда и больше никуда.
      </div>

      <h4 class="dim mini" style="padding:10px 10px 6px">СЕССИИ</h4>
      <div id="sessionList"></div>

      <h4 class="dim mini" style="padding:10px 10px 6px">ПАПКИ РАБОТЫ</h4>
      <div id="wsList2"></div>
      <div id="wsHint"></div>
    </div>

    <!-- вкладка СТАТУС

         Живёт всегда, а не по нажатию: состояние моделей меняется само
         каждые 12 минут, и если смотреть на него только по кнопке, то
         «модель ожила» замечают через полчаса. -->
    <div class="psec" id="p-status">
      <!-- Мощность в аккаунтах, а не в моделях. Десять моделей на одном
           выбитом ключе — это ноль; девять аккаунтов OpenRouter — это
           девять моделей, работающих параллельно. -->
      <div class="autoBox" id="keyBox"></div>
      <div class="autoBox" id="autoBox"></div>
      <!-- Лазарет: те же модели, но разложенные по палатам. Таблица
           пишет «limited» — непонятно; палата пишет «на лечении,
           до выписки 4:12» — понятно, и ждать не страшно. -->
      <div class="autoBox" id="wardBox"></div>
      <div class="row tight">
        <button class="btn sm pri" id="pingBtn" onclick="pingAll()">Пинг всех</button>
        <button class="btn sm" onclick="pingUnavailable()">Пинг недоступных</button>
        <button class="btn sm" onclick="scan()">Обновить каталог</button>
        <button class="btn sm" onclick="sanityAll()">Проверить ответы</button>
        <!-- Голос статуса: конец задачи вслух. Выключен по умолчанию,
             состояние — в localStorage, без сервера и без запросов. -->
        <button class="btn sm" id="voiceBtn" onclick="voiceToggle()">🔈 голос: выкл</button>
      </div>
      <div class="hintBlock" style="margin:8px 12px">
        Автоматическая проверка сама пингует недоступные модели раз в 12 минут
        и коротким запросом — иначе модель может ждать лимита по часу, а вы
        об этом не узнаете. Ручной «Пинг всех» нужен после смены ключей.
      </div>
      <div id="pingOut"></div>
      <div id="sanityOut"></div>
    </div>

    <!-- Вкладка ОЧЕРЕДЬ. Кнопка-вкладка у неё была, а разметка — нет:
         `.psec` скрыт, пока на секции нет `.on`, а `ltab()` ставит `.on` только
         по имени нажатой вкладки. Секция без вкладки не открывалась никогда,
         и вместе с ней были недостижимы кнопки «одобрить план» и «ответить»,
         которые `renderTasks()` рисует именно здесь: задача в статусе
         `asking` висела до перезапуска. -->
    <div class="psec" id="p-queue">
      <div id="taskList"></div>
    </div>

    <!-- вкладка ЛОКАЛЬНЫЕ МОДЕЛИ

         Чат с моделями, которые живут на этом же компьютере (Ollama).
         Отдельный разговор, а не задача агенту: локальная модель не
         умеет ходить по файлам и звать инструменты, зато не тратит
         квоту и работает без интернета. Ответ приходит потоком, слова
         за словом, — локальная модель думает секундами, и молчание
         без потока выглядит как зависание. -->

    <div class="psec" id="p-local" hidden>
      <div class="row tight" style="padding:8px 10px">
        <select id="localModel" style="flex:1"></select>
        <button class="btn sm" onclick="localClear()">Очистить</button>
        <span class="mini dim" id="localMsg"></span>
      </div>
      <div id="localChat"
           style="max-height:52vh;overflow:auto;padding:8px 10px"></div>
      <div class="row tight" style="padding:8px 10px;border-top:1px solid var(--dim)">
        <textarea id="localText" rows="2" style="flex:1"
                  placeholder="Спросите локальную модель (Enter — отправить, Shift+Enter — строка)"></textarea>
        <button class="btn sm pri" id="localSend" onclick="localSend()">Спросить</button>
      </div>
    </div>

    <!-- вкладка ГАЙДЫ ПО API

         Сводка firsthand-проверок от 2026-10-07: где брать ключи, лимиты
         free-тарифов, гео-красные флаги (кому нужен VPN) и готовый curl.
         Полная машинная версия — update/Api-guide.txt. -->
    <div class="psec" id="p-guide">
      <div class="mgroup">
        <h4>Нужен ли VPN? (проверено 07.10.2026 с IP РФ)</h4>
        <div class="kv">
          <div>✅ без VPN: Z.ai, Mistral, Cloudflare, llm7, Zen</div>
          <div>⚠️ нестабильно: Groq (403 с части подсетей)</div>
          <div>🔒 только VPN: OpenRouter, NVIDIA, Google Gemini</div>
        </div>
        <div class="mini dim" style="padding:4px 10px 8px">
          403 «security policy» / 451 / 400 «User location» — это блок по
          региону, а не битый ключ: не удаляйте ключ, включите VPN и повторите.
        </div>
      </div>

      <div class="mgroup">
        <h4>Z.ai / GLM — ✅ работает без VPN</h4>
        <dl class="kv">
          <dt>регистрация</dt><dd>z.ai → email, без карты</dd>
          <dt>ключ</dt><dd>z.ai/manage-apikey/apikey-list → Create API Key (показывается один раз)</dd>
          <dt>формат</dt><dd>&lt;id&gt;.&lt;secret&gt; одной строкой</dd>
          <dt>free</dt><dd>glm-4.7-flash, glm-4.5-flash, glm-4.6v-flash — бессрочно</dd>
        </dl>
        <pre>curl https://api.z.ai/api/paas/v4/chat/completions \
  -H "Authorization: Bearer $Z_AI_KEY" -H "Content-Type: application/json" \
  -d '{"model":"glm-4.5-flash","messages":[{"role":"user","content":"hi"}]}'</pre>
        <div class="row tight" style="padding:0 10px 8px">
          <button class="btn sm pri" data-copy="curl https://api.z.ai/api/paas/v4/chat/completions -H &quot;Authorization: Bearer $Z_AI_KEY&quot; -H &quot;Content-Type: application/json&quot; -d &apos;{&quot;model&quot;:&quot;glm-4.5-flash&quot;,&quot;messages&quot;:[{&quot;role&quot;:&quot;user&quot;,&quot;content&quot;:&quot;hi&quot;}]}'" onclick="copyAttr(this,'curl')">копировать curl</button>
        </div>
        <div class="mini dim" style="padding:0 10px 8px">Пустой text при малом max_tokens — это reasoning съел бюджет: ставьте 2000+.</div>
      </div>

      <div class="mgroup">
        <h4>Mistral La Plateforme — ✅ работает без VPN</h4>
        <dl class="kv">
          <dt>регистрация</dt><dd>console.mistral.ai → email/Google/GitHub</dd>
          <dt>ключ</dt><dd>console.mistral.ai/api-keys → Create new key</dd>
          <dt>формат</dt><dd>mstrl_...</dd>
          <dt>free</dt><dd>~$10 кредитов/мес, ~1 RPS: ministral-3b/8b, codestral</dd>
        </dl>
        <pre>curl https://api.mistral.ai/v1/chat/completions \
  -H "Authorization: Bearer $MISTRAL_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"ministral-3b-latest","messages":[{"role":"user","content":"hi"}]}'</pre>
        <div class="mini dim" style="padding:4px 10px 8px">
          401 «This is a paid model» = модель не для free-плана, ключ жив.
          Opt-out из обучения: Settings → выключить «Allow data training».
        </div>
      </div>

      <div class="mgroup">
        <h4>Cloudflare Workers AI — ✅ работает без VPN</h4>
        <dl class="kv">
          <dt>регистрация</dt><dd>dash.cloudflare.com/sign-up, без карты</dd>
          <dt>account id</dt><dd>дашборд → Workers AI → Use REST API</dd>
          <dt>токен</dt><dd>profile/api-tokens → Create Token → шаблон «Workers AI API Token» (НЕ Global API Key!)</dd>
          <dt>формат</dt><dd>cfut_... + Account ID (нужны ОБА)</dd>
          <dt>free</dt><dd>10 000 neurons/день, сброс 00:00 UTC; сверх — запрос падает, не биллингует</dd>
        </dl>
        <pre>curl "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT/ai/v1/chat/completions" \
  -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  -d '{"model":"@cf/openai/gpt-oss-20b","messages":[{"role":"user","content":"hi"}]}'</pre>
      </div>

      <div class="mgroup">
        <h4>llm7.io — ✅ без ключа и без VPN</h4>
        <dl class="kv">
          <dt>доступ</dt><dd>анонимный: turbo-модели (GLM-5.3-Flash, gpt-oss:20b, DeepSeek-V4-Flash)</dd>
          <dt>токен</dt><dd>token.llm7.io — бесплатно, поднимает лимиты (60 RPM, 100K токенов/сутки)</dd>
          <dt>лимиты</dt><dd>анонимно ~10 RPM / 60 запросов/час</dd>
        </dl>
        <pre>curl https://api.llm7.io/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"GLM-5.3-Flash","messages":[{"role":"user","content":"hi"}]}'</pre>
        <div class="mini dim" style="padding:4px 10px 8px">Каталог моделей ротируется: модель может исчезнуть. Статус: status.llm7.io</div>
      </div>

      <div class="mgroup">
        <h4>OpenCode Zen — ✅ без ключа, одна модель</h4>
        <dl class="kv">
          <dt>без ключа</dt><dd>только space-bunny-free (проверено, cost=0)</dd>
          <dt>остальное</dt><dd>-free модели дают 403 «only from within OpenCode» — гейтвей проверяет origin родного CLI</dd>
        </dl>
        <pre>curl https://opencode.ai/zen/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"space-bunny-free","messages":[{"role":"user","content":"hi"}]}'</pre>
      </div>

      <div class="mgroup">
        <h4>Groq — ⚠️ нестабильно (403 с части IP)</h4>
        <dl class="kv">
          <dt>регистрация</dt><dd>console.groq.com → Google/GitHub/email, без карты</dd>
          <dt>ключ</dt><dd>console.groq.com/keys → Create API Key</dd>
          <dt>формат</dt><dd>gsk_...</dd>
          <dt>free</dt><dd>~30 RPM / 1000 RPD: gpt-oss-120b/20b, qwen3.8-27b</dd>
        </dl>
        <pre>curl https://api.groq.com/openai/v1/chat/completions \
  -H "Authorization: Bearer $GROQ_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"openai/gpt-oss-20b","messages":[{"role":"user","content":"hi"}],"max_tokens":2000}'</pre>
        <div class="mini dim" style="padding:4px 10px 8px">При 403 сменить IP. Reasoning-модели: max_tokens 2000+, иначе пустой ответ.</div>
      </div>

      <div class="mgroup">
        <h4>OpenRouter — 🔒 только VPN (403 security policy с IP РФ)</h4>
        <dl class="kv">
          <dt>регистрация</dt><dd>openrouter.ai → Google/GitHub/email</dd>
          <dt>ключ</dt><dd>openrouter.ai/settings/keys → Create Key</dd>
          <dt>формат</dt><dd>sk-or-v1-...</dd>
          <dt>free</dt><dd>модели с суффиксом :free; 20 RPM / 50 RPD; депозит $10 → 1000 RPD</dd>
        </dl>
        <pre>curl https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "HTTP-Referer: http://localhost" -H "X-Title: zagent" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen/qwen3.8-27b:free","messages":[{"role":"user","content":"hi"}]}'</pre>
        <div class="mini dim" style="padding:4px 10px 8px">402 = у модели кончился бесплатный пул на сегодня. Free-модели логируют промпты.</div>
      </div>

      <div class="mgroup">
        <h4>NVIDIA NIM — 🔒 только VPN (451)</h4>
        <dl class="kv">
          <dt>регистрация</dt><dd>build.nvidia.com → аккаунт NVIDIA, без карты</dd>
          <dt>ключ</dt><dd>на странице модели «Get API Key» или build.nvidia.com/settings/api-keys (показывается один раз)</dd>
          <dt>формат</dt><dd>nvapi-...</dd>
          <dt>free</dt><dd>40 RPM, дневного лимита нет (кредиты отменены)</dd>
        </dl>
        <pre>curl https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer $NVIDIA_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"meta/llama-3.1-8b-instruct","messages":[{"role":"user","content":"hi"}]}'</pre>
      </div>

      <div class="mgroup">
        <h4>Google Gemini — 🔒 только VPN, ключ новый</h4>
        <dl class="kv">
          <dt>регистрация</dt><dd>aistudio.google.com → кнопка Get API key</dd>
          <dt>формат</dt><dd>AQ.... (новый формат с 2025, не AIza)</dd>
          <dt>free</dt><dd>Flash ~15 RPM / 1500 RPD; Pro 2–5 RPM / 25–50 RPD; контекст до 1M</dd>
          <dt>модели</dt><dd>актуальна gemini-3.8-flash; линейка 2.5 закрыта для новых аккаунтов (404)</dd>
        </dl>
        <pre>curl https://generativelanguage.googleapis.com/v1beta/openai/chat/completions \
  -H "Authorization: Bearer $GOOGLE_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"gemini-3.8-flash","messages":[{"role":"user","content":"hi"}]}'</pre>
        <div class="mini dim" style="padding:4px 10px 8px">
          Ошибка 400 «User location is not supported» = геоблок, ключ жив.
          RPD обновляется ~10:00 МСК. Для агентных цепочек RPM маловат — Gemini
          лучше как консультант, а не основной конвейер.
        </div>
      </div>

      <div class="mgroup">
        <h4>Ollama — локально, VPN не нужен</h4>
        <dl class="kv">
          <dt>установка</dt><dd>ollama.com/download, затем ollama pull qwen3:8b</dd>
          <dt>endpoint</dt><dd>http://localhost:11434/v1 (OpenAI-совместимый, ключа нет)</dd>
        </dl>
      </div>

      <div class="mgroup">
        <h4>Куда класть ключи</h4>
        <div class="mini" style="padding:2px 10px 8px">
          config/secrets.local.json (в .gitignore), формат — список для ротации:
          "groq": ["gsk_...", ...]. Несколько ключей = карантин по 429 работает
          автоматически. Полный гайд для агентов: update/Api-guide.txt
        </div>
      </div>
    </div>

  </div>
</div>

<div class="grip" id="gripL" style="flex:0 0 5px"></div>

<!-- ================= ЦЕНТР ================= -->
<div class="pane" id="center">
  <div class="phead">
    <span id="chatTitle">Агент</span>
    <div class="spacer"></div>
    <span class="mini muted" id="chatInfo"></span>
    <button class="btn sm" onclick="clearChat()">очистить</button>
  </div>
  <!-- Панель частей работы: пока части идут, видно, над чем каждая
     работает; когда отработали — сворачивается. -->
  <div id="subsBox" class="subsBox"></div>
  <!-- План роя: кто на каком аккаунте и кто в резерве. Появляется, когда
       включён режим роя. -->
  <div id="herdBox" class="herdBox"></div>
  <!-- Полоса хода задачи: что агент делает прямо сейчас, сколько шагов и
       токенов потрачено и сколько ещё есть. Без неё длинная задача выглядит
       как зависшая: последнее, что видно, — давний вызов инструмента. -->
  <div id="progBar" class="progBar" hidden></div>
  <div id="msgs"></div>
  <div id="composer">
    <div id="attach"></div>

    <!-- Выбор модели у поля ввода: видно всегда, а не только на отдельной
         вкладке. Раньше режим и модель прятались во вкладке «Модели», а это
         единственное место, где видно, кто будет выполнять задачу. -->
    <div class="modelRow">
      <span id="modelBadge"></span>
      <button class="btn sm" id="modeBtn" onclick="openModePick()">Режим: обычный ⌄</button>
      <div class="spacer"></div>
      <label class="mini muted" style="display:flex;gap:5px;align-items:center">
        <input type="checkbox" id="visionChk" style="width:auto"> vision-модели
      </label>
      <label class="mini muted" style="display:flex;gap:5px;align-items:center">
        <input type="checkbox" id="planChk" style="width:auto"
               onchange="TASK_FLAGS.plan = this.checked; renderModeBtn()"> сначала план
      </label>
    </div>
    <div id="modelPick" hidden></div>
    <div id="modePick" hidden></div>
    <div id="autoNote"></div>
    <div id="subPanel"></div>

    <textarea id="cbox" placeholder="Опишите задачу. Enter — отправить, Shift+Enter — новая строка."
      onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send();}"></textarea>
    <div id="cfoot">
      <button class="btn sm" onclick="document.getElementById('fileIn').click()">📎 файл</button>
      <button class="btn sm" onclick="takeShot()">📷 экран</button>
      <input type="file" id="fileIn" style="display:none" accept="image/*" multiple
             onchange="addFiles(this.files)">
      <div class="spacer"></div>
      <span class="mini muted" id="sendInfo"></span>
      <button class="btn sm" onclick="stopTask()" id="stopBtn" style="display:none">стоп</button>
      <button class="btn pri swapBtn" onclick="send()">
        <span class="sb-tx">Отправить</span><span class="sb-ic">→</span>
      </button>
    </div>
  </div>
</div>

<div class="grip" id="gripR" style="flex:0 0 5px"></div>

<!-- ================= СПРАВА ================= -->
<!-- Правая панель — только просмотр файлов. Раньше здесь была вторая вкладка
     «Модели и пинг» с дублем того, что уже слева: два места с одним и тем же,
     и второе всегда выглядело забытым. -->
<div class="pane" id="right">
  <div class="phead">
    <span class="pheadTitle">Файлы</span>
    <span class="dim mini" id="fsPath"></span>
    <div class="spacer"></div>
    <button class="btn sm" onclick="loadTree(fCur)" title="вверх">↑</button>
    <button class="btn sm" onclick="loadTree('.')" title="в корень">⌂</button>
    <button class="btn sm" onclick="loadTree(fCur)" title="обновить">↻</button>
  </div>
  <div class="fcrumbs" id="fcrumbs"></div>
  <div class="pbody" id="p-files" style="display:flex;flex-direction:column">
    <div id="ftree" style="flex:0 0 46%;overflow:auto;border-bottom:1px solid var(--edge)"></div>
    <div id="fview" style="flex:1;overflow:auto"></div>
  </div>
</div>

</div>
</div>

<!-- диалог разрешения на выход за воркспейс -->
<div id="bell" onclick="showPermission()"></div>
<div id="modal">
  <div id="modalBox">
    <div class="mh"><span class="ic">🔐</span><span id="permTitle">Нужно разрешение</span></div>
    <div class="mb">
      <div class="q" id="permQuestion"></div>
      <div class="mp" id="permPath"></div>
      <div class="hint">
        Агент хочет выйти за пределы воркспейса. «Только сейчас» разрешит
        этот путь в текущей задаче, «Всегда» — во всех следующих.
      </div>
    </div>
    <div class="mf">
      <button class="btn" onclick="decidePermission(false,'once')">Отклонить</button>
      <div class="grow"></div>
      <button class="btn" onclick="decidePermission(true,'always')">Всегда разрешить</button>
      <button class="btn pri" onclick="decidePermission(true,'once')">Только сейчас</button>
    </div>
  </div>
</div>

<!-- Свой диалог вместо родного prompt(): тот подавляется во встроенных
     браузерах, из-за чего кнопка «новая сессия» выглядела сломанной. -->
<div class="dlgWrap" id="dlg" hidden>
  <div class="dlg">
    <div class="dlgTitle" id="dlgTitle"></div>
    <div class="dlgText" id="dlgText"></div>
    <div id="dlgExtra"></div>
    <input id="dlgInput" autocomplete="off" spellcheck="false">
    <div class="dlgFoot">
      <button class="btn" id="dlgCancel">Отмена</button>
      <button class="btn pri" id="dlgOk">OK</button>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
// `S` — состояние с сервера. Изначально пустой объект, а не null: событие из
// потока приходит раньше первого ответа на /api/state, и любое обращение к
// `S.candidates` в этот момент было TypeError. Он гасил обработчик события
// целиком, и список моделей оставался пустым до следующего обновления.
let S = {}, GUIDE = null, ATTACH = [], lastEvent = 0, curTask = null;
let CUR_PERM = null;

// Ход текущей задачи для полосы прогресса.
//
// Отдельное состояние, а не вычисление по журналу: журнал показывает всё
// подряд, включая прошлые задачи, и «сейчас агент читает вот этот файл» из
// него не выводится — там нет понятия «сейчас».
const PROG = {
  active: false, tool: '', file: '', steps: 0, maxSteps: 0,
  tokens: 0, budget: 0, note: '', quiet: false,
};

function fmtTokens(n) {
  n = Number(n || 0);
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return Math.round(n / 1000) + 'k';
  return String(n);
}

// Полоса: слева — чем занят агент сейчас, дальше — расход шагов и токенов.
function renderProgress() {
  const box = $('progBar');
  if (!box) return;
  if (!PROG.active) { box.hidden = true; box.innerHTML = ''; return; }
  box.hidden = false;

  const stepPct = PROG.maxSteps
    ? Math.min(100, Math.round(PROG.steps * 100 / PROG.maxSteps)) : 0;
  const tokPct = PROG.budget
    ? Math.min(100, Math.round(PROG.tokens * 100 / PROG.budget)) : 0;

  const now = PROG.note
    || (PROG.file ? `${PROG.tool} · ${PROG.file}` : PROG.tool)
    || 'думает';

  box.innerHTML =
    `<span class="progNow" title="${esc(now)}">${esc(now)}</span>` +
    (PROG.maxSteps
      ? `<span class="progTrack" title="шаги ${PROG.steps} из ${PROG.maxSteps}">
           <div class="progFill" style="width:${stepPct}%"></div></span>
         <span class="progNum">шаги ${PROG.steps}/${PROG.maxSteps}</span>`
      : '') +
    (PROG.budget
      ? `<span class="progTrack" title="токены ${PROG.tokens} из ${PROG.budget}">
           <div class="progFill ${tokPct > 80 ? 'warn' : ''}"
                style="width:${tokPct}%"></div></span>
         <span class="progNum">токены ${fmtTokens(PROG.tokens)}/${fmtTokens(PROG.budget)}</span>`
      : '');
}

function progressOff() {
  PROG.active = false;
  PROG.tool = ''; PROG.file = ''; PROG.note = '';
  PROG.quiet = false; QUIET_SHOWN = false;
  PROG.steps = 0; PROG.maxSteps = 0; PROG.tokens = 0; PROG.budget = 0;
  renderProgress();
}

// lastEvent хранится между перезагрузками. Без этого поток начинался с нуля
// и сервер отдавал всю историю событий: до 200 чужих записей, каждая тянула
// ещё и /api/state. Итог — до 400 параллельных запросов при пустом экране.
// sessionStorage, а не localStorage: история нужна только этой вкладке,
// и после закрытия вкладки продолжать старую ленту незачем.
const EVT_KEY = 'zagent.lastEvent';
try {
  const saved = Number(sessionStorage.getItem(EVT_KEY) || 0);
  if (saved > 0) lastEvent = saved;
} catch { /* приватный режим: просто начнём с нуля */ }

function rememberEvent(id) {
  if (!(id > lastEvent)) return;
  lastEvent = id;
  LAST_EVENT_AT = Date.now();
  try { sessionStorage.setItem(EVT_KEY, String(id)); } catch { /* переживём */ }
}

// Отличать работу от зависания.
//
// Пока идёт задача, события идут постоянно. Если их нет дольше двух минут,
// перед нами либо очень долгий запрос модели, либо уже мёртвый процесс, и
// по журналу это не различить — оба выглядят одинаково тихо. Здесь честно
// сказано «тишина идёт N секунд», чтобы человек решал сам, а не гадал по
// отсутствию строк. Молчание не всегда поломка: бесплатные модели думают
// по минуте и дольше, и ложная тревога научила бы игнорировать настоящую.
const QUIET_AFTER_MS = 120000;
let LAST_EVENT_AT = Date.now();
let QUIET_SHOWN = false;

function watchQuiet() {
  const box = $('progBar');
  if (!box || !PROG.active) { QUIET_SHOWN = false; return; }
  const quiet = Date.now() - LAST_EVENT_AT > QUIET_AFTER_MS;
  if (quiet === QUIET_SHOWN) return;
  QUIET_SHOWN = quiet;
  if (quiet && !PROG.quiet) {
    PROG.quiet = true;
    PROG.note = 'тишина больше 2 минут — возможно завис, возможно долгий запрос';
  } else if (!quiet && PROG.quiet) {
    PROG.quiet = false;
    PROG.note = '';
  }
  renderProgress();
}
setInterval(watchQuiet, 5000);
// Прогресс замера доступности из России. directDone — сделан ли первый замер:
// без него второй бессмыслен, поэтому кнопка блокируется.
let GEO = {running:false, progress:{done:0,total:0,current:'',phase:''},
           log:[], directDone:false};
// Состояние автоматической проверки моделей: когда была, что ожило, что
// делать дальше. Заполняется из /api/ping/status.
let PING = {running:false, interval:0, last:0, since:null, next_in:null,
            history:[], recovered:{}};

// Уже показанные события. Подписка включается до чтения backlog, поэтому
// событие на границе приходит дважды: сначала из истории, потом из очереди.
// Без этой проверки в переписке появлялись парные шаги.
const seen = new Set();

// Множество не должно расти вечно: вкладка может висеть сутки, и тогда
// память уйдёт на миллион чисел. Держим последние 2000 id.
const SEEN_MAX = 2000;
function noteSeen(id) {
  if (seen.size >= SEEN_MAX) {
    // Удаляем самое старое: множество хранит порядок вставки.
    seen.delete(seen.values().next().value);
  }
  seen.add(id);
}

// ---------- диалог разрешения ----------
async function checkPermissions() {
  const r = await api('/api/permissions', {});
  const list = r.permissions || [];
  if (!list.length) { CUR_PERM = null; $('modal').classList.remove('on');
                      $('bell').classList.remove('on'); return; }

  const next = list[0];
  if (!CUR_PERM || CUR_PERM.id !== next.id) {
    CUR_PERM = next;
    $('permTitle').textContent = 'Нужно разрешение на выход из воркспейса';
    $('permQuestion').textContent = next.reason ||
      `Агент собирается выполнить «${next.operation}» по пути вне воркспейса.`;
    $('permPath').textContent = next.path;
    $('modal').classList.add('on');
    $('bell').textContent = '🔐 Нужно разрешение (' + list.length + ')';
    $('bell').classList.add('on');
  }
}
function showPermission() { $('modal').classList.add('on'); }
async function decidePermission(allow, scope) {
  if (!CUR_PERM) return;
  const id = CUR_PERM.id;
  $('modal').classList.remove('on');
  $('bell').classList.remove('on');
  CUR_PERM = null;
  await api('/api/permissions', {action:'answer', permission_id:id, allow, scope});
  toast(allow
    ? (scope === 'always' ? 'Разрешено навсегда' : 'Разрешено для этой задачи')
    : 'Отклонено — агент получит отказ');
  refresh();
}
$('modal').addEventListener('click', e => {
  // Клик по затемнённому фону закрывает диалог без решения.
  if (e.target.id === 'modal') { /* ждём явного решения */ }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && $('modal').classList.contains('on') && CUR_PERM) {
    decidePermission(false, 'once');
  }
});

// ---------- утилиты ----------
// Строка для подстановки в JS-литерал внутри HTML-атрибута.
function esc(s) { return String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
// Строка для подстановки в JS-литерал внутри HTML-атрибута (onclick и т.п.).
// esc() здесь не годится: он кладёт &#39;, а парсер декодирует сущности до
// компиляции JS и апостроф снова рвёт литерал. Сначала экранируем спецсимволы
// JS, потом HTML — так атрибут не разрывается, а JS получает целую строку.
function jsq(s) {
  return esc(String(s ?? '')
    .replace(/\\/g, '\\\\')
    .replace(/'/g, '\\u0027')
    .replace(/\r/g, '\\r')
    .replace(/\n/g, '\\n')
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e'));
}
function chip(v) { return `<span class="chip ${esc(v)}">${esc(v)}</span>`; }
async function api(path, body) {
  // try на всём запросе, а не только на разборе JSON: раньше отказ
  // сети или упавший сервер вылетал из функции наверх, и вызывающие
  // оставались с вечно «ставлю в очередь…» и без следующего refresh.
  let r;
  try {
    r = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: {'Content-Type':'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body)
    });
  } catch (e) {
    return {ok:false, error:'сервер недоступен (' + (e && e.message || e) + ')'};
  }
  try { return await r.json(); }
  catch { return {ok:false, error:'плохой ответ сервера'}; }
}
// Данные для обработчика кладутся в data-атрибут, а не внутрь onclick.
//
// `esc()` для этого недостаточно, и это не мелочь: апостроф в esc()
// превращается в `&#39;`, а HTML-парсер декодирует сущности **до** компиляции
// JavaScript — то есть `&#39;` снова становится `'` и рвёт строку. Перевод
// строки esc() не трогает вовсе, а содержимое файла и текст инструкции
// многострочные. Итог был один: кнопки «копировать» не работали ни разу, а
// имя файла с апострофом ломало разметку.
//
// Через атрибут значение доходит целым: браузер сам декодирует сущности при
// разборе, и в JS попадает ровно то, что было в исходнике.
function copyAttr(el, what) { copy(el.getAttribute('data-copy') || '', what); }
function argAttr(el) { return el.getAttribute('data-arg') || ''; }

async function copy(text, what) {
  try { await navigator.clipboard.writeText(text); toast('Скопировано: ' + what); }
  catch { // буфер может быть недоступен без https
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove();
    toast('Скопировано: ' + what);
  }
}
function toast(msg) {
  addMsg({who:'zagent', text:msg, kind:'sys'});
}

// ---------- свои диалоги вместо prompt/confirm ----------
//
// Родные prompt() и confirm() не годились: они блокируют страницу, выглядят
// как чужое окно посреди интерфейса, а в части окружений (встроенный браузер,
// запуск без окна) вообще подавляются — кнопка «новая сессия» выглядела как
// сломанная, хотя на сервере всё работало. Свои диалоги ведут себя одинаково
// везде и дают выбрать папку без ручного набора пути.

// Диалог с одним полем ввода. Возвращает строку или null при отмене.
function askText(title, value, opts) {
  const o = opts || {};
  return new Promise(resolve => {
    const dlg = document.getElementById('dlg');
    $('dlgTitle').textContent = title;
    const input = $('dlgInput');
    input.value = value || '';
    input.placeholder = o.placeholder || '';
    input.style.display = o.noInput ? 'none' : '';
    $('dlgText').textContent = o.text || '';
    $('dlgText').style.display = o.text ? '' : 'none';
    $('dlgExtra').style.display = o.extra ? '' : 'none';
    if (o.extra) $('dlgExtra').innerHTML = o.extra;
    $('dlgOk').textContent = o.okText || 'OK';
    dlg.hidden = false;
    setTimeout(() => {
      if (o.noInput) $('dlgOk').focus();
      else { input.focus(); input.select(); }
    }, 20);

    const close = answer => {
      dlg.hidden = true;
      input.removeEventListener('keydown', onKey);
      resolve(answer);
    };
    const accept = () => close(o.noInput ? true : input.value);
    const onKey = ev => {
      if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); accept(); }
      if (ev.key === 'Escape') { ev.preventDefault(); close(null); }
    };
    input.addEventListener('keydown', onKey);
    $('dlgOk').onclick = accept;
    $('dlgCancel').onclick = () => close(null);
  });
}

// Выбор папки: системный диалог, если браузер умеет, иначе ввод пути.
// showDirectoryPicker есть в Chromium и требует запуска из обработчика
// события пользователя — поэтому он вызывается напрямую, без await до него.
async function askFolder(title) {
  if (window.showDirectoryPicker) {
    try {
      const dir = await window.showDirectoryPicker({mode: 'readwrite'});
      return dir.name ? (await dirPath(dir)) : null;
    } catch (err) {
      if (err && err.name === 'AbortError') return null;
      // Остальные ошибки (нет прав, отказ) не должны мешать ручному вводу.
    }
  }
  return askText(title || 'Путь к папке', '', {
    placeholder: 'C:\\work\\my-project',
    text: 'Вставьте путь к папке. Агент не сможет выйти за её пределы.',
  });
}

// У handle нет пути в виде строки: собираем по именам. Права на запись не
// запрашиваем — их запросил бы сам picker, а нам нужно только имя папки.
async function dirPath(handle) {
  const parts = [];
  let node = handle;
  while (node) { parts.unshift(node.name); node = node.parent; }
  // Имя диска уходит вместе с остальным путём: для `C:\Users\HP\x`
  // возвращалось `Users\HP\x`, сервер резолвил это относительно своей
  // рабочей папки, пути не находил и предлагал **создать** его — то
  // есть внутри проекта вырастало мусорное дерево. Корни вида «Диск C:»
  // и «home» при этом отбрасываются: они не часть пути.
  const trimmed = parts[0].startsWith('Диск') || parts[0] === 'home'
    ? parts.slice(1) : parts;
  return trimmed.join('\\');
}

// Подтверждение с пояснением. Возвращает true/false.
function askYes(title, text) {
  return askText(title, '', {text, noInput: true, okText: 'Да'}).then(v => v === true);
}
function addMsg(m) {
  const box = $('msgs');
  const d = document.createElement('div');
  d.className = 'msg ' + (m.kind || 'assistant');
  const meta = [m.who, m.model, m.ms != null ? m.ms + ' мс' : null]
    .filter(Boolean).map(esc).join(' · ');
  d.innerHTML = `<div class="who">${meta}</div><div class="body">${esc(m.text)}</div>`;
  box.appendChild(d);
  box.scrollTop = box.scrollHeight;
}

// Что агент создал за задачу — ссылки, а не просто список файлов.
//
// Ответ агента состоит из текста с путями в обратных кавычках, и чтобы
// посмотреть результат, надо было вручную найти папку и открыть файл.
// Здесь каждый созданный файл становится ссылкой: слева — просмотр кода
// в панели справа, справа — открытие в браузере для страниц и разметки.
function renderArtifacts(list) {
  const rows = (list || []).filter(a => a && a.path);
  if (!rows.length) return;

  const openable = rows.filter(a => a.open);
  const title = openable.length
    ? 'Открыть результат'
    : 'Создано за задачу';
  let html = `<div class="arts"><div class="artsHead">${title}</div>`;

  for (const a of rows) {
    const isDir = a.kind === 'dir';
    const name = a.path.split('/').filter(Boolean).pop() || a.path;
    html += '<div class="artRow">';
    html += `<span class="artIcon">${isDir ? '▸' : '·'}</span>`;
    // Просмотр есть у всего, что интерфейс умеет показывать.
    // Путь — в data-атрибут, а не в onclick. JSON.stringify внутри
    // атрибута, уже обрамлённого кавычками, ломал разметку на
    // любом имени файла с кавычкой внутри.
    html += `<a class="artName" href="#" data-art="${esc(a.path)}"`
      + ` title="показать в панели справа">${esc(name)}</a>`;
    if (a.open) {
      html += `<a class="artGo" href="${esc(a.open)}" target="_blank"`
        + ` rel="noopener" title="открыть в браузере">открыть ↗</a>`;
    } else if (!isDir) {
      html += '<span class="artHint">правый клик по файлу в дереве — открыть в браузере</span>';
    }
    html += '</div>';
  }
  html += '</div>';
  const box = $('msgs');
  box.insertAdjacentHTML('beforeend', html);
  // Клик по ссылке вешаем явно: путь лежит в data-art, а не в onclick,
  // где кавычка в имени файла закрывала бы атрибут.
  box.querySelectorAll('[data-art]').forEach(el => {
    el.addEventListener('click', ev => showArtifact(ev, el.dataset.art));
  });
  box.scrollTop = box.scrollHeight;
}

// Показать созданный файл в панели справа: и код, и результат в одном месте.
function showArtifact(ev, path) {
  if (ev) ev.preventDefault();
  openEntry(path, /\/$/.test(path));
}

// ---------- локальные модели (Ollama) ----------
// История живёт в браузере и целиком уходит в каждый запрос: локальный
// рантайм не помнит ничего между вызовами, поэтому «память» разговора
// держим мы. Отдельный массив, чтобы не мешать переписке агента.
let LOCAL_MSG = [];
let LOCAL_BUSY = false;

async function loadLocalModels(force) {
  const box = $('localModel'), note = $('localMsg');
  const r = await api('/api/local/models');
  // Сервер отвечает 200 даже когда рантайм выключен: «не запущен» — это
  // состояние, которое надо показать словами, а не ошибкой.
  if (!r.ok || !r.running) {
    if (note) note.textContent = (r && r.error) || 'Ollama не запущен (ollama serve)';
    if (box) box.innerHTML = '<option value="">— нет моделей —</option>';
    return;
  }
  const keep = box ? box.value : '';
  if (box) {
    box.innerHTML = r.models.map(m =>
      `<option value="${esc(m.id)}">${esc(m.id)}` +
      `${m.parameters ? ' · ' + esc(m.parameters) : ''}` +
      `${m.size_gb ? ' · ' + esc(m.size_gb) + ' ГБ' : ''}</option>`
    ).join('') || '<option value="">— нет моделей —</option>';
    if (keep && r.models.some(m => m.id === keep)) box.value = keep;
  }
  if (note) note.textContent = `${r.models.length} моделей · локально, без квоты`;
}

function localBubble(role, text) {
  const box = $('localChat');
  const div = document.createElement('div');
  div.className = role === 'user' ? 'msg user' : 'msg assistant';
  div.style.cssText = 'max-width:82%;padding:9px 12px;border-radius:10px;' +
    'margin:6px 0;white-space:pre-wrap;line-height:1.45;' +
    (role === 'user'
      ? 'background:#2563eb;color:#fff;margin-left:auto'
      : 'background:#1b1f28;border:1px solid var(--dim)');
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}

async function localSend() {
  const input = $('localText'), model = $('localModel').value;
  const text = input.value.trim();
  if (!text || LOCAL_BUSY) return;
  if (!model) { setNote('localMsg', 'сначала выберите модель', false); return; }

  LOCAL_BUSY = true;
  $('localSend').disabled = true;
  input.value = '';
  LOCAL_MSG.push({role: 'user', content: text});
  localBubble('user', text);
  const out = localBubble('assistant', '');

  try {
    const resp = await fetch('/api/local/chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model, messages: LOCAL_MSG}),
    });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '', full = '', failed = '';
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {stream: true});
      // Поток режет ответ по переводу строки целиком: часть строки между
      // чтениями — это ещё не событие, и разбирать её рано.
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        const line = part.split('\n').find(l => l.startsWith('data: '));
        if (!line) continue;
        const payload = line.slice(6).trim();
        if (payload === '[DONE]') continue;
        const ev = JSON.parse(payload);
        if (ev.error) { failed = ev.error; continue; }
        full += ev.text || '';
        out.textContent = full;
        $('localChat').scrollTop = $('localChat').scrollHeight;
      }
    }
    if (failed) out.textContent += '\n[ошибка: ' + failed + ']';
    if (full.trim()) LOCAL_MSG.push({role: 'assistant', content: full});
  } catch (e) {
    out.textContent += '\n[ошибка соединения: ' + e.message + ']';
  } finally {
    LOCAL_BUSY = false;
    $('localSend').disabled = false;
    input.focus();
  }
}

function localClear() {
  LOCAL_MSG = [];
  $('localChat').innerHTML = '';
  loadLocalModels();
}

// Enter отправляет, Shift+Enter — новая строка. Поведение то же, что у
// основного поля ввода: человек не должен запоминать два правила.
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.shiftKey) return;
  const box = e.target;
  if (box && box.id === 'localText') {
    e.preventDefault();
    localSend();
  }
});

// ---------- вкладки ----------
function ltab(name) {
  document.querySelectorAll('#left .ptab').forEach(t =>
    t.classList.toggle('on', t.dataset.p === name));
  document.querySelectorAll('#left .psec').forEach(s =>
    s.classList.toggle('on', s.id === 'p-' + name));
  // Настройки тянут свежие счётчики при каждом открытии: ключи могли
  // добавиться извне (правка файла руками, второй экземпляр софта).
  if (name === 'settings') loadSettings();
  // Список локальных моделей меняется на лету: `ollama pull` могли
  // выполнить, пока вкладка была закрыта.
  if (name === 'local') loadLocalModels();
}
// В правой панели была вторая вкладка «Модели и пинг» — дубль того, что уже
// слева. Она убрана, поэтому переключателя вкладок здесь больше нет. Функция
// оставлена как заглушка: на неё могли ссылаться старые вызовы.
function rtab(name) {
  if (name === 'conn') {
    // Дубль переехал в отдельную вкладку «Статус» слева.
    ltab('status');
  }
}

// Переключатель модели рядом с полем ввода: выбор виден всегда, а не
// только на вкладке «Модели». Это то, чем агент пользуется на самом деле.
function renderModelBadge() {
  const box = $('modelBadge');
  if (!box) return;
  const sel = selState();
  const ref = sel.current || '';
  const model = (S.candidates || []).find(r => r.ref === ref);
  const name = model ? model.model : (ref ? ref.split('/').slice(-1)[0] : 'выбирается');
  const manual = sel.mode === 'manual';

  box.innerHTML = `<button class="mBadge" onclick="toggleModelPick()"
      title="${esc(manual ? 'Ручной выбор модели. Нажмите, чтобы вернуть авто.' :
                         'Авто-выбор лучшей доступной модели. Нажмите, чтобы выбрать вручную.')}">
      <span class="kind">${manual ? 'вручную' : 'авто'}</span>
      <span class="nm">${esc(name)}</span>
      <span class="caret">▾</span>
    </button>`;
  const panel = $('modelPick');
  if (panel) {
    panel.innerHTML = `
      <div class="mpMode">
        <span class="isw${manual ? '' : ' on'}" onclick="setMode('auto')"
              title="авто: агент сам берёт лучшую доступную"></span>
        <span>авто — лучшая доступная</span>
      </div>
      <div class="mpHead">
        <span class="dim mini">Модель для агента (${(S.candidates||[]).length})</span>
        <span class="linkish" onclick="toggleModelPick()">закрыть</span>
      </div>
      <div class="mpSearch"><input id="pickFilter" placeholder="Фильтр…"
           oninput="renderModelPick()"></div>
      <div class="mpList" id="pickList"></div>`;
  }
}

// Выпадающий список моделей под полем ввода.
function toggleModelPick() {
  const panel = $('modelPick');
  if (!panel) return;
  $('modePick')?.setAttribute('hidden', '');
  const open = panel.hasAttribute('hidden');
  if (open) { renderModelPick(); panel.removeAttribute('hidden'); }
  else panel.setAttribute('hidden', '');
}

// ---------- режимы работы ----------
//
// Режим выбирается у поля ввода, рядом с моделью: и то и другое определяет,
// как пойдёт задача, и прятать это в настройках значит забыть включить.
//
// По умолчанию стоит «Авто»: решение принимает программа. Причина простая —
// требование выбрать режим перед каждой задачей превращается либо в
// лишние секунды, либо в привычку жать «обычный» не глядя, и тогда режимы
// существуют, но никогда не включаются.

const MODES = {
  auto: {
    title: 'Авто',
    note: 'Сам выберу, что нужно: поиск в интернете, субагенты или обычный ход. ' +
          'Покажу, что выбрал и почему.',
  },
  plain: {
    title: 'Обычный режим',
    note: 'Один агент, одна модель, без поиска в интернете. Подходит почти всем задачам.',
  },
  selfdev: {
    title: 'Разработка софта',
    note: 'Агент правит код самого zagent: читает исходники, меняет их и ' +
          'проверяет тестами. Включайте, когда нужно чинить или дорабатывать программу.',
    warn: 'Агент будет менять файлы, по которым работает. Сделайте коммит перед задачей.',
    needsWorkspace: 'код zagent',
  },
  subagents: {
    title: 'Субагенты',
    note: 'Главный агент разбивает задачу на части и поручает их нескольким ' +
          'моделям параллельно, затем собирает результат и делает выжимку.',
    warn: 'Расходует токены в несколько раз быстрее: каждая часть — отдельный запрос.',
  },
  research: {
    title: 'Веб-разведка',
    note: 'Агент ищет в интернете, читает найденное и опирается на источники ' +
          'со ссылками, а не на память модели.',
  },
  swarm: {
    title: 'Разведка + субагенты',
    note: 'Сначала несколько моделей ищут информацию по частям, потом главный ' +
          'агент собирает выжимку и выполняет задачу с опорой на неё.',
  },
  herd: {
    title: 'Рой агентов',
    note: 'Большую задачу делают сразу много рабочих, каждый на своём ' +
          'аккаунте. Аккаунты делятся по частям, часть мощности остаётся ' +
          'резервом, выбывшего подменяют — и работа продолжается с места, ' +
          'где остановилась. Главный агент не ждёт всех: он делает то, что ' +
          'можно, пока части идут.',
    warn: 'Темп запросов ограничен намеренно: рой шлёт много запросов сразу, ' +
          'и без ограничения это выглядит для провайдера как злоупотребление.',
    needsAccounts: 4,
  },
};

let CUR_MODE = 'auto';

// Какие режимы задачи уже включены. Хранятся здесь, а не в настройках:
// режим относится к конкретной задаче, и незачем помнить его до следующего
// запуска программы.
const TASK_FLAGS = {
  auto: true, plan: false, selfdev: false, subagents: false, research: false,
  herd: false,
};

// Что «Авто» выбрал для последней задачи. Показывается рядом с кнопкой
// режима: решение без объяснения выглядит как произвол, и человек после
// одного странного выбора выключает «Авто» навсегда.
let AUTO_PICK = null;

function currentModeLabel() {
  if (TASK_FLAGS.auto) return 'авто';
  const on = [];
  if (TASK_FLAGS.herd) on.push('рой');
  if (TASK_FLAGS.selfdev) on.push('разработка софта');
  if (TASK_FLAGS.subagents) on.push('субагенты');
  if (TASK_FLAGS.research) on.push('веб-разведка');
  if (TASK_FLAGS.plan) on.push('сначала план');
  return on.length ? on.join(' + ') : 'обычный';
}

function renderModeBtn() {
  const btn = $('modeBtn');
  if (!btn) return;
  btn.textContent = 'Режим: ' + currentModeLabel() + ' ⌄';
  btn.classList.toggle('on', TASK_FLAGS.subagents || TASK_FLAGS.research
                              || TASK_FLAGS.herd);
  renderAutoNote();
}

// Строка под кнопкой: что «Авто» решил и почему.
function renderAutoNote() {
  const box = $('autoNote');
  if (!box) return;
  if (!TASK_FLAGS.auto) { box.innerHTML = ''; return; }
  if (!AUTO_PICK) {
    box.innerHTML = '<span class="dim mini">Режим выберу сам и напишу, почему</span>';
    return;
  }
  const p = AUTO_PICK;
  box.innerHTML = `<span class="mini">Выбрано: <b>${esc(p.mode || 'обычный')}</b>` +
    (p.reason ? ` · ${esc(p.reason)}` : '') +
    (p.source === 'heuristic' ? ' <span class="dim">(по признакам в тексте)</span>' : '') +
    '</span>';
}

function openModePick() {
  const panel = $('modePick');
  if (!panel) return;
  $('modelPick')?.setAttribute('hidden', '');
  if (!panel.hasAttribute('hidden')) { panel.setAttribute('hidden', ''); return; }
  renderModeCards();
  panel.removeAttribute('hidden');
}

// Карточки перерисовываются на месте, без переоткрытия панели. Иначе клик по
// карточке закрывал окно, и человек не видел, что режим поменялся: выглядело
// так, будто кнопка не сработала.
function renderModeCards() {
  const panel = $('modePick');
  if (!panel) return;

  // У каждой карточки свой флаг состояния. Раньше он выводился из позиции в
  // массиве, и «Субагенты» показывали состояние веб-разведки: карточка
  // выглядела включённой, когда включали совсем другое.
  //
  // «Разработка софта» (`selfdev`) в списке намеренно нет: правку собственного
  // кода агентом пока не включаем. Описание режима и вся логика на сервере на
  // месте — вернуть карточку достаточно добавить её в этот список.
  const cards = [
    ['auto', 'auto'],
    ['plain', ''],
    ['herd', 'herd'],
    ['subagents', 'subagents'],
    ['research', 'research'],
    ['swarm', 'swarm'],
  ].map(([key, flag]) => {
    const m = MODES[key];
    const power = keyPower();
    // Рой требует аккаунтов: без них он не рой, а очередь. Карточка
    // остаётся доступной, но сразу говорит, чего не хватает — иначе человек
    // выбрал бы режим и узнал о проблеме через полчаса работы.
    //
    // Пока состояние не пришло, предупреждения нет: «0 из 0» — это не
    // «аккаунтов нет», это «ещё не спросили», и человек увидел бы ложное
    // требование отключить то, что на самом деле доступно.
    const short = m.needsAccounts && power.total > 0
                  && power.free < m.needsAccounts;
    const on = (() => {
    // При включённом «Авто» отмечена только карточка «Авто». Раньше признак
    // считался как «не субагенты и не разведка», и при «Авто» обычный режим
    // тоже выглядел включённым: две галочки на одном невозможном выборе.
    if (TASK_FLAGS.auto) return flag === 'auto';
    if (flag === 'swarm') return TASK_FLAGS.subagents && TASK_FLAGS.research;
    return flag ? !!TASK_FLAGS[flag]
                : !(TASK_FLAGS.subagents || TASK_FLAGS.research || TASK_FLAGS.herd);
  })();
    return `<div class="modeCard${on ? ' on' : ''}" onclick="setTaskMode('${key}')">
      <div class="mcHead">${esc(m.title)}
        ${on ? '<span class="mcOn">включён</span>' : ''}</div>
      <div class="mcNote">${esc(m.note)}</div>
      ${short ? `<div class="mcWarn">Свободных аккаунтов ${power.free} из ${power.total}, а рою нужно минимум ${m.needsAccounts}. Рой будет работать вхолостую — возьми субагентов.</div>` : ''}
      ${m.warn ? `<div class="mcWarn">${esc(m.warn)}</div>` : ''}
    </div>`;
  }).join('');

  panel.innerHTML = `<div class="mpHead">
      <span class="dim mini">Как выполнять задачу</span>
      <span class="linkish" onclick="openModePick()">закрыть</span>
    </div><div class="modeList">${cards}</div>`;
}

// Переключить режим задачи.
//
// Имя не `setMode`: это имя уже занято переключателем выбора модели
// (авто/вручную). Вторая декларация молча перетирала первую, и клик по
// карточке уходил в выбор модели с аргументом `plain` — то есть ровно
// ничего не менял, а выглядело как зависшая кнопка.
async function setTaskMode(key) {
  const m = MODES[key];
  if (!m) return;

  if (key === 'auto') {
    // «Авто» снимает все остальные флаги: иначе получится «реши сам, но
    // ещё и обязательно ищи в интернете», и режим перестаёт решать что-то.
    TASK_FLAGS.auto = true;
    TASK_FLAGS.selfdev = false;
    TASK_FLAGS.subagents = false;
    TASK_FLAGS.research = false;
    TASK_FLAGS.herd = false;
  } else if (key === 'plain') {
    TASK_FLAGS.auto = false;
    TASK_FLAGS.selfdev = false;
    TASK_FLAGS.subagents = false;
    TASK_FLAGS.research = false;
    TASK_FLAGS.herd = false;
    TASK_FLAGS.plan = false;
    $('planChk').checked = false;
  } else if (key === 'herd') {
    // Рой — не «субагенты побольше»: у него свои правила распределения
    // аккаунтов, есть резерв и подмена выбывшего. Отдельный флаг, и он
    // снимает остальные: смешивать два режима в одном прогоне — значит
    // получить ни то ни другое.
    TASK_FLAGS.auto = false;
    TASK_FLAGS.herd = true;
    TASK_FLAGS.subagents = false;
    TASK_FLAGS.research = false;
    TASK_FLAGS.selfdev = false;
  } else if (key === 'swarm') {
    TASK_FLAGS.auto = false;
    TASK_FLAGS.subagents = true;
    TASK_FLAGS.research = true;
    TASK_FLAGS.selfdev = false;
    renderSubPanel();
  } else if (key === 'selfdev') {
    // Правка собственного кода — единственный режим, где агент трогает
    // программу, внутри которой работает. Подтверждение здесь обязательно:
    // последствий больше, чем у любой другой настройки.
    const ws = activeWorkspace();
    const yes = await askYes('Разработка софта',
      'Агент будет менять код самого zagent.\n\n' +
      (ws ? 'Рабочая папка: ' + ws.path + '\n\n' : '') +
      'Сделайте коммит перед задачей: откатить изменения можно будет только так.');
    if (!yes) { renderModeCards(); return; }
    TASK_FLAGS.auto = false;
    TASK_FLAGS.selfdev = !TASK_FLAGS.selfdev;
  } else if (key === 'subagents') {
    TASK_FLAGS.auto = false;
    TASK_FLAGS.subagents = !TASK_FLAGS.subagents;
    renderSubPanel();
  } else if (key === 'research') {
    TASK_FLAGS.auto = false;
    TASK_FLAGS.research = !TASK_FLAGS.research;
    renderSubPanel();
  }

  renderModeBtn();
  renderSubPanel();
  renderModeCards();
}

function activeWorkspace() {
  const ws = (S && S.workspaces) || {};
  return (ws.workspaces || []).find(x => x.id === ws.active) || null;
}

// Сколько аккаунтов свободно прямо сейчас.
//
// Считается из `S.keys.summary`, который присылает сервер вместе с остальным
// состоянием. Раньше здесь стоял `KEY_RING.snapshot()` — имя существует
// только в Python (в `worker.key_stats`), а в браузере оно всегда было
// `undefined`. Падение случалось на каждом `refresh()`, то есть всегда:
// режимы выглядели нерабочими, а в консоли лежал ReferenceError.
function keyPower() {
  const sum = ((S && S.keys) || {}).summary || {};
  return {
    free: Number(sum.free_keys || 0),
    total: Number(sum.total_keys || 0),
  };
}

// Блок интерфейса субагентов: карточки, след, разворот.
//
// Отдельным файлом, потому что вставляется в большой шаблон `ui.py` целиком,
// а править его по кускам через командную строку неудобно и опасно.

const SUBS = {};

function subsBox() {
  let box = $('subsBox');
  if (box) return box;
  box = document.createElement('div');
  box.id = 'subsBox';
  box.className = 'subsBox';
  const msgs = $('msgs');
  (msgs && msgs.parentElement ? msgs.parentElement : msgs).appendChild(box);
  return box;
}

function subCardHtml(sub, data) {
  const files = (data.files || []).join(', ') || 'файлы не указаны';
  return `<div class="subCard" data-sub="${esc(sub)}">
    <div class="subHead" onclick="toggleSub('${jsq(sub)}')">
      <span class="subDot"></span>
      <span class="subName">${esc(sub)}</span>
      <span class="subTitle">${esc(data.title || '')}</span>
      <span class="subModel"></span>
      <span class="subStat mini dim" data-role="stat"></span>
      <span class="subMore mini">след ▾</span>
    </div>
    <div class="subWhy mini"></div>
    <div class="subNow mini" data-role="now"></div>
    <div class="subFiles mini dim">свои файлы: ${esc(files)}</div>
    <div class="subTrail" data-role="trail" hidden></div>
  </div>`;
}

function ensureSub(sub, data) {
  if (!sub) return null;
  if (!SUBS[sub]) {
    // rows — один упорядоченный список всего, что делала часть. Раньше
    // запросы к модели, вызовы инструментов и шаги лежали в трёх списках,
    // и след собирался из них по группам: сначала все вызовы, потом все
    // запросы, потом все шаги. Порядок, в котором часть на самом деле
    // работала, при этом терялся — а именно он и нужен, чтобы понять,
    // почему агент написал именно этот код.
    SUBS[sub] = {part: data || {}, rows: [], model: '', tool: '', file: '',
                tokens: 0};
  } else if (data) {
    Object.assign(SUBS[sub].part, data);
  }
  const box = subsBox();
  const sel = '[data-sub="' + CSS.escape(sub) + '"]';
  let el = box.querySelector(sel);
  if (!el) {
    box.insertAdjacentHTML('beforeend', subCardHtml(sub, SUBS[sub].part));
    el = box.querySelector(sel);
    SUBS[sub].el = el;
  }
  const title = el && el.querySelector('.subTitle');
  if (title && SUBS[sub].part.title) title.textContent = SUBS[sub].part.title;
  return el;
}

function toggleSub(sub) {
  const item = SUBS[sub];
  if (!item || !item.el) return;
  const trail = item.el.querySelector('[data-role="trail"]');
  if (!trail) return;
  const open = trail.hasAttribute('hidden');
  if (open) { trail.innerHTML = trailHtml(item); trail.removeAttribute('hidden'); }
  else trail.setAttribute('hidden', '');
  const more = item.el.querySelector('.subMore');
  if (more) more.textContent = open ? 'след ▴' : 'след ▾';
}

// Длинный текст свёрнут, короткий показан целиком: иначе блок превращается
// в простыню, и главное — что модель ответила — в ней не видно.
function longText(text, label) {
  const body = esc(text || '');
  if (body.length <= 400) return `<div class="trailMsg">${body}</div>`;
  return `<details class="trailMore"><summary>${esc(label)} (${body.length} знаков)</summary>
    <pre class="trailPre">${body}</pre></details>`;
}

function trailHtml(item) {
  if (!item.rows.length) return '<div class="trailEmpty">следа пока нет</div>';
  return item.rows.map(rowHtml).join('');
}

// Одна строка следа. Вид зависит от того, что произошло, но порядок всегда
// тот, в котором события действительно шли.
function rowHtml(row) {
  const n = row.n;
  if (row.kind === 'call') {
    const f = row.file || '';
    return `<div class="trailRow">
      <div class="trailHead">${n}. вызов ${esc(row.tool || '')}${f ? ' · ' + esc(f) : ''}</div>
      <pre class="trailPre">${esc(JSON.stringify(row.args || {}).slice(0, 1200))}</pre>
      ${row.result ? longText(JSON.stringify(row.result), 'ответ инструмента') : ''}
    </div>`;
  }
  if (row.kind === 'step') {
    return `<div class="trailRow"><div class="trailHead">${n}. ${
      esc(row.text || row.phase || '')}</div></div>`;
  }
  const sent = (row.sent || []).map(m => {
    const c = typeof m.content === 'string' ? m.content : JSON.stringify(m.content);
    return `[${m.role}] ${String(c).slice(0, 4000)}`;
  }).join('\n\n');
  return `<div class="trailRow">
    <div class="trailHead">${n}. запрос к модели${
      row.model ? ' · ' + esc(row.model) : ''}</div>
    ${longText(sent, 'что ушло')}
    ${row.text ? longText(row.text, 'что вернулось') : ''}
    ${row.error ? `<div class="trailBad">ошибка: ${esc(row.error)}</div>` : ''}
  </div>`;
}

function subLiveStat(sub) {
  const item = SUBS[sub];
  if (!item || !item.el) return;
  const stat = item.el.querySelector('[data-role="stat"]');
  if (!stat) return;
  const bits = [];
  const prompts = item.rows.filter(r => r.kind === 'prompt').length;
  const calls = item.rows.filter(r => r.kind === 'call').length;
  if (item.model) bits.push(item.model.split('/').pop());
  if (prompts) bits.push(`запросов ${prompts}`);
  if (calls) bits.push(`вызовов ${calls}`);
  stat.textContent = bits.join(' · ');
  subLiveNow(sub);
}

// Чем конкретная часть занята прямо сейчас. Без этой строки у десяти
// частей был один и тот же счётчик запросов, и понять, кто завис, а кто
// работает, было невозможно — а это ровно то, что нужно при разборе роя.
function subLiveNow(sub) {
  const item = SUBS[sub];
  if (!item || !item.el) return;
  const box = item.el.querySelector('[data-role="now"]');
  if (!box) return;
  const done = !!(item.part && item.part.ok !== undefined && item.part.ok !== null);
  if (done) { box.textContent = ''; return; }
  const bits = [];
  if (item.tool) bits.push(item.tool + (item.file ? ' · ' + item.file : ''));
  else if (item.model) bits.push(item.model.split('/').pop() + ' думает');
  else bits.push('начало');
  if (item.tokens) bits.push(`токенов ${fmtTokens(item.tokens)}`);
  box.textContent = bits.join(' · ');
  box.title = box.textContent;
}

function pushRow(sub, row) {
  const item = SUBS[sub];
  if (!item) return;
  row.n = item.rows.length + 1;
  item.rows.push(row);
  // Открытый след дополняется на ходу: человек, который развернул его,
  // чтобы посмотреть, не должен перерисовывать вручную после каждого шага.
  const trail = item.el && item.el.querySelector('[data-role="trail"]');
  if (trail && !trail.hasAttribute('hidden')) {
    const empty = trail.querySelector('.trailEmpty');
    if (empty) empty.remove();
    trail.insertAdjacentHTML('beforeend', rowHtml(row));
    trail.scrollTop = trail.scrollHeight;
  }
}

// Событие части. Возвращает true, когда событие принадлежит части и в общей
// переписке рисовать его не нужно: иначе шаги всех частей дублировались бы
// в журнале вперемешку с шагами главного агента, и разобрать их было бы
// невозможно.
function onSubEvent(e) {
  const sub = e.sub || '';
  if (!sub) return false;
  if (e.type === 'part_assigned') {
    const el = ensureSub(sub, e.part || {});
    const why = el && el.querySelector('.subWhy');
    if (why) why.textContent = (e.assignment && e.assignment.why) || '';
    const model = el && el.querySelector('.subModel');
    if (model) model.textContent = (e.assignment && e.assignment.ref) || '';
    if (el) el.classList.toggle('wait', !!(e.assignment && e.assignment.admitted === false));
    return true;
  }
  if (e.type === 'part_started') { ensureSub(sub, e.part || {}); subLiveStat(sub); return true; }
  if (e.type === 'part_done') {
    const el = ensureSub(sub, e.part || {});
    if (el) {
      el.classList.toggle('ok', !!(e.part && e.part.ok));
      el.classList.toggle('bad', !!(e.part && e.part.ok === false));
    }
    subLiveStat(sub);
    return true;
  }
  if (e.type === 'tool') {
    ensureSub(sub, null);
    const f = e.file || e.path || '';
    const toolRow = {kind: 'call', tool: e.tool, args: e.args, result: e.result};
    if (f) toolRow.file = f;
    pushRow(sub, toolRow);
    const item = SUBS[sub];
    if (item) { item.tool = e.tool || ''; item.file = f; }
    subLiveStat(sub);
    return true;
  }
  if (e.type === 'model_call') {
    ensureSub(sub, null);
    const got = e.got || {};
    if (got.model) SUBS[sub].model = got.model;
    if (e.tokens != null) SUBS[sub].tokens = Number(e.tokens) || 0;
    // Запрос ушёл, ответа ещё нет — модель сейчас занята именно им.
    const item = SUBS[sub];
    if (item) { item.tool = 'думает'; item.file = ''; }
    pushRow(sub, {kind: 'prompt', sent: e.sent, model: got.model,
                  text: got.text, error: e.error});
    subLiveStat(sub);
    return true;
  }
  if (e.type === 'step') {
    ensureSub(sub, null);
    const step = e.step || {};
    if (e.tokens != null) SUBS[sub].tokens = Number(e.tokens) || 0;
    pushRow(sub, {kind: 'step', text: step.text, phase: step.phase});
    subLiveStat(sub);
    return true;
  }
  return false;
}

// Панель субагентов сворачивается, когда все части отработали: карточки
// нужны в процессе, а после занимают место в переписке. След остаётся
// доступен по клику — разбор иногда нужен и после задачи.
function collapseSubs() {
  const box = $('subsBox');
  if (box) box.classList.add('done');
}

// План роя: кто на каком аккаунте и кто в резерве.
//
// Отдельный блок от карточек частей. Карточки показывают работу, план —
// распределение ресурсов: смешивать незачем, это разные вопросы.
const HERD = {plan: null};

function herdBox() {
  let box = $('herdBox');
  if (box) return box;
  box = document.createElement('div');
  box.id = 'herdBox';
  box.className = 'herdBox';
  const anchor = $('subsBox');
  (anchor && anchor.parentElement ? anchor.parentElement : anchor).appendChild(box);
  return box;
}

function renderHerdPlan(plan) {
  HERD.plan = plan || null;
  const box = herdBox();
  if (!plan) { box.innerHTML = ''; return; }
  // Хвост аккаунта обязателен: у рабочих и резервных слотов одного шлюза
  // модель и шлюз совпадают, и без хвоста они выглядят одинаковыми. По
  // хвосту видно и что подмена ушла на другой аккаунт, а не на соседний
  // слот того же шлюза.
  const rows = (list, cls) => list.map(s => `<div class="herdSlot ${cls}"
      title="${esc(s.ref)}${s.key_tail ? ' · аккаунт …' + esc(s.key_tail) : ''}${s.note ? ' — ' + esc(s.note) : ''}">
      <span class="hsRef">${esc(s.ref)}</span>
      ${s.key_tail ? `<span class="hsKey">…${esc(s.key_tail)}</span>` : ''}
      <span class="hsOwner">${esc(s.taken_by || 'резерв')}</span>
    </div>`).join('');
  box.innerHTML = `<div class="herdGroup">рабочие</div>
    <div class="herdList">${rows(plan.workers || [], 'busy') || '<span class="dim mini">нет</span>'}</div>
    <div class="herdGroup">резерв</div>
    <div class="herdList">${rows(plan.reserve || [], 'idle') || '<span class="dim mini">нет</span>'}</div>`;
}

function renderSubPanel() {
  const box = $('subPanel');
  if (!box) return;
  if (!TASK_FLAGS.subagents && !TASK_FLAGS.research) {
    box.innerHTML = '';
    return;
  }

  const power = keyPower();

  let html = '<div class="subBox">';
  if (TASK_FLAGS.subagents) {
    html += `<div class="subRow"><span class="srName">Субагентов одновременно</span>
      <select id="subCount" onchange="SUB.count = Number(this.value); renderSubPanel()">
        ${[2,3,4,5,6,8].map(n =>
          `<option value="${n}" ${n === SUB.count ? 'selected' : ''}>${n}</option>`).join('')}
      </select></div>`;
    html += `<div class="subHint">${esc(SUB.rationale)}</div>`;
  }
  if (TASK_FLAGS.research) {
    html += `<div class="subRow"><span class="srName">Источников на разведку</span>
      <select id="resCount" onchange="RESEARCH.count = Number(this.value); renderSubPanel()">
        ${[2,3,4,5,6].map(n =>
          `<option value="${n}" ${n === RESEARCH.count ? 'selected' : ''}>${n}</option>`).join('')}
      </select></div>`;
  }
  html += `<div class="subWarn">Свободных аккаунтов: ${power.free} из ${power.total}. ` +
    'Субагенты работают параллельно, и каждый занимает свой аккауннт; ' +
    'при нехватке часть заданий будет ждать.</div></div>';
  box.innerHTML = html;
}

// Настройки режимов. Считаются от числа свободных аккаунтов: субагент — это
// отдельный запрос, и больше их, чем аккаунтов, делать бессмысленно.
const SUB = {count: 3, depth: 1, rationale: ''};
const RESEARCH = {count: 3};

function tuneModes() {
  const free = keyPower().free;
  // Пока состояние не пришло, берём середину: ноль аккаунтов не значит
  // «субагентов быть не может» — это значит «ещё не знаем».
  const cap = Math.max(2, Math.min(8, free || 3));
  if (SUB.count > cap) SUB.count = cap;
  if (SUB.count < 2) SUB.count = 2;
  SUB.rationale = free === 0
    ? 'Счёт аккаунтов ещё не пришёл с сервера — показываю среднее значение.'
    : (free >= 4
        ? 'Аккаунтов хватает, чтобы часть заданий шла параллельно.'
        : `Свободных аккаунтов ${free}: часть субагентов будет ждать своей очереди.`);
  const resCap = Math.max(2, Math.min(6, free || 3));
  if (RESEARCH.count > resCap) RESEARCH.count = resCap;
  renderSubPanel();
}

function renderModelPick() {
  const box = $('pickList');
  if (!box) return;
  const needle = ($('pickFilter')?.value || '').trim().toLowerCase();
  let rows = S.candidates || [];
  if (needle) {
    rows = rows.filter(r => (r.model || '').toLowerCase().includes(needle) ||
                            (r.ref || '').toLowerCase().includes(needle));
  }
  const sel = selState();
  if (!rows.length) {
    box.innerHTML = `<div class="empty">${needle ? 'Ничего не найдено' : 'Реестр пуст'}</div>`;
    return;
  }
  box.innerHTML = rows.map(r => {
    const p = r.probe || {};
    const state = p.status || r.status || 'unknown';
    const on = sel.manual_ref === r.ref;
    const cur = sel.current === r.ref;
    return `<div class="mpRow${on ? ' on' : ''}" data-ref="${esc(r.ref)}"
                 onclick="pickModel(this)">
      <span class="radio">${on ? '◉' : '○'}</span>
      <span class="nm">${esc(r.model)}</span>
      ${cur && !on ? '<span class="chip info mini">сейчас</span>' : ''}
      ${r.vision ? '<span class="chip info" style="font-size:9px">👁</span>' : ''}
      ${ruBadge(r)}
      ${chip(state)}
    </div>`;
  }).join('');
}

// ---------- разделители панелей ----------
(function setupGrips() {
  // Разбор в try: значение в localStorage можно испортить самому
  // (или старой версией записать иначе), и раньше такая ошибка
  // роняла весь скрипт на верхнем уровне — вместе с навешиванием
  // всех остальных обработчиков.
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('zagent.layout') || '{}') || {}; }
  catch (e) { saved = {}; }
  if (saved.lw) document.documentElement.style.setProperty('--lw', saved.lw + 'px');
  if (saved.rw) document.documentElement.style.setProperty('--rw', saved.rw + 'px');

  function drag(gripId, paneId, cssVar, min, max, key) {
    const grip = $(gripId), pane = $(paneId);
    grip.addEventListener('mousedown', ev => {
      ev.preventDefault();
      grip.classList.add('drag');
      document.body.classList.add('resizing');
      const startX = ev.clientX;
      const startW = pane.getBoundingClientRect().width;
      const sign = paneId === 'right' ? -1 : 1;

      function move(e) {
        const w = Math.max(min, Math.min(max,
          startW + sign * (e.clientX - startX)));
        pane.style.flex = `0 0 ${w}px`;
      }
      function up() {
        grip.classList.remove('drag');
        document.body.classList.remove('resizing');
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
        const w = Math.round(pane.getBoundingClientRect().width);
        document.documentElement.style.setProperty(cssVar, w + 'px');
        pane.style.flex = '';
        const layout = JSON.parse(localStorage.getItem('zagent.layout') || '{}');
        layout[key] = w;
        localStorage.setItem('zagent.layout', JSON.stringify(layout));
      }
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });
  }
  drag('gripL', 'left',  '--lw', 220, 620, 'lw');
  drag('gripR', 'right', '--rw', 260, 780, 'rw');
})();

// ---------- модели ----------
function renderModels() {
  const list = $('modelList');
  if (!list) return;
  const all = (S.candidates || []);
  if (!all.length) { list.innerHTML = '<div class="empty">\u0420\u0435\u0435\u0441\u0442\u0440 \u043f\u0443\u0441\u0442. \u041d\u0430\u0436\u043c\u0438\u0442\u0435 «\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c \u043a\u0430\u0442\u0430\u043b\u043e\u0433».</div>'; return; }

  const needle = ($('modelFilter')?.value || '').trim().toLowerCase();
  const cands = needle
    ? all.filter(r => (r.model || '').toLowerCase().includes(needle) ||
                      (r.ref || '').toLowerCase().includes(needle))
    : all;
  if (needle && !cands.length) {
    list.innerHTML = `<div class="empty">\u041d\u0438\u0447\u0435\u0433\u043e \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e: ${esc(needle)}</div>`;
    return;
  }

  const manual = selState().mode === 'manual';
  const current = selState().manual_ref || '';

  // В ручном режиме модель одна, и она выбирается здесь — это и есть
  // отсутствовавшая функция. Клик по строке назначает модель агента.
  let html = manual ? '<h4 class="dim mini" style="margin:10px 12px 4px">\u0412\u042b\u0411\u0415\u0420\u0418\u0422\u0415 \u041c\u041e\u0414\u0415\u041b\u042c \u0414\u041b\u042f \u0410\u0413\u0415\u041d\u0422\u0410</h4>' : '';

  for (const r of cands) {
    const p = r.probe || {};
    const stt = p.status || r.status || 'unknown';
    const ms = p.duration_ms ? (p.duration_ms/1000).toFixed(1)+'s' : '\u2014';
    const on = current === r.ref;
    html += `<div class="mrow${on ? ' on' : ''}" data-ref="${esc(r.ref)}"
                 onclick="pickModel(this)">
      <span class="radio">${on ? '\u25c9' : '\u25cb'}</span>
      <span class="nm">${esc(r.model)}</span>
      <span class="dim mini gw">${esc(r.gateway)}</span>
      ${r.vision ? '<span class="chip info" style="font-size:9px">\ud83d\udc41</span>' : ''}
      ${ruBadge(r)}
      ${chip(stt)}
      <span class="sz">${ms}</span>
    </div>`;
  }
  list.innerHTML = html;

  if (!GUIDE) return;
  renderGateways();
}

// Клик по строке модели назначает её агента. Работает в обоих режимах:
// в auto клик переключает на ручной выбор — иначе он выглядел бы
// безответным, а именно ручной выбор и нужен.
async function pickModel(node) {
  const ref = node?.dataset?.ref;
  if (!ref) return;
  const r = await api('/api/mode', {mode: 'manual', manual_ref: ref});
  if (!r.ok) {
    toast(r.error || 'не получилось выбрать модель');
    return;
  }
  // Показываем выбранную строку сразу: refresh() занимает до секунды, и без
  // этого клик выглядит проигнорированным.
  node.classList.add('on');
  const dot = node.querySelector('.radio');
  if (dot) dot.textContent = '◉';
  renderModeNote();
  toast('Модель агента: ' + ref);
  refresh();
}

// Состояние селектора: режим (auto/manual) и выбранная модель.
//
// Имя selState, а не st: короткое st использовалось как локальная переменная
// в refresh() и перекрывало одноимённую функцию — весь интерфейс замирал после
// первого обновления. Функция объявлена здесь, рядом с первым её
// использованием: когда её потеряли, ни одна проверка этого не заметила,
// потому что синтаксис оставался корректным.
function selState() { return (S && S.selector) || {}; }

// Ключи и адреса шлюзов — отдельным блоком: для работы агента они не нужны.
function renderGateways() {
  const box = $('gwList');
  if (!box) return;
  const byGateway = {};
  for (const r of (S.candidates || [])) (byGateway[r.gateway] ||= []).push(r);

  let html = '';
  for (const [gw, rows] of Object.entries(byGateway)) {
    const info = (GUIDE?.connections || []).find(c => c.gateway === gw) || {};
    const ok = rows.filter(r => ['ok','slow'].includes(r.probe?.status || r.status)).length;
    html += `<div class="mgroup">
      <h4>${esc(info.label || gw)} <span class="dim">\u00b7 ${ok}/${rows.length} \u0440\u0430\u0431\u043e\u0442\u0430\u044e\u0442</span></h4>
      <dl class="kv">
        <dt>provider id</dt><dd class="copy" onclick="copy('${jsq(info.provider_id || gw)}','provider id')">${esc(info.provider_id || gw)}</dd>
        <dt>base URL</dt><dd class="copy" onclick="copy('${jsq(info.base_url || '')}','base URL')">${esc(info.base_url || '')}</dd>
        ${info.keyless
          ? '<dt>\u043a\u043b\u044e\u0447</dt><dd class="dim">\u043d\u0435 \u043d\u0443\u0436\u0435\u043d</dd>'
          : `<dt>api key</dt><dd class="copy" onclick="copyKey('${jsq(gw)}')">${info.api_key
              ? esc(info.api_key.slice(0,10)) + '\u2026' + esc(info.api_key.slice(-4))
              : '<span class="dim">\u043d\u0435 \u0437\u0430\u0434\u0430\u043d</span>'}</dd>
            <dt>\u043f\u0435\u0440\u0435\u043c\u0435\u043d\u043d\u0430\u044f</dt><dd class="copy" onclick="copy('${jsq(info.env_var || '')}','\u0438\u043c\u044f \u043f\u0435\u0440\u0435\u043c\u0435\u043d\u043d\u043e\u0439')">${esc(info.env_var || '')}</dd>`}
      </dl>
      <div class="mini dim" style="padding:0 12px 6px">${rows.map(r => esc(r.model)).join(', ')}</div>
    </div>`;
  }
  box.innerHTML = html || '<div class="empty">\u0428\u043b\u044e\u0437\u043e\u0432 \u043d\u0435\u0442</div>';
}

// Раскрывающийся блок. Принимает либо заголовок, либо id тела.
//
// Раньше fold() искал блок только по id, и вызовы вида fold('fTools') падали: такого
// id уже не было. Теперь заголовок знает своё тело через
// соседний элемент, и несработаивое дело не ронитается.
function fold(what) {
  const head = (what && what.classList?.contains('foldHead'))
    ? what
    : (typeof what === 'string' ? $(what)?.previousElementSibling : null);
  if (!head) return;
  const body = head.nextElementSibling;
  if (!body || !body.classList.contains('foldBody')) return;

  const open = body.hasAttribute('hidden');
  if (open) body.removeAttribute('hidden'); else body.setAttribute('hidden', '');
  const icon = head.querySelector('.foldIc');
  if (icon) icon.textContent = open ? '\u25be' : '\u25b8';
}

// ---------- настройки: ключи и модели ----------
//
// Вкладка живёт на /api/settings. Сервер отдаёт только имена полей и
// счётчики: значений ключей в ответе нет по построению, и в разметке
// они не должны появиться ни в одном месте — ни в списке, ни в плейсхолдере.

let SETTINGS = null;

// Режим разработчика. Отдельное состояние от SETTINGS: ключи и модели —
// это про конфигурацию шлюзов, режим разработчика — про саму установку,
// и перезагружать одно из-за другого незачем (заодно вкладка Настроек
// не мигает при каждом открытии).
let DEV = null;

// ---------- все модели: статус и общий вопрос ----------
//
// Отладчик должен показывать не «шлюз отвечает», а каждую модель
// отдельно: донорские идут через мост на 8784, локальные — из Ollama,
// и сервер сводит их в один ответ (/api/models/status).
let MODELS_STATE = null, modelsBusy = false;

const MODEL_STATES = {
  ok:       {text:'отвечает',      cls:'ok'},
  local:    {text:'локально',      cls:'ok'},
  fail:     {text:'отказала',      cls:'bad'},
  cooling:  {text:'на остывании',  cls:'warn'},
  unknown:  {text:'не проверена',  cls:'dim'},
};

function modelStateMark(state) {
  const item = MODEL_STATES[state] || MODEL_STATES.unknown;
  return `<span class="chip ${item.cls}">${esc(item.text)}</span>`;
}

async function modelsStatus() {
  const box = $('modelsBox'), msg = $('modelsMsg');
  if (msg) msg.textContent = 'спрашиваю мост…';
  if (box) box.hidden = false;
  const r = await api('/api/models/status');
  MODELS_STATE = r;
  if (msg) msg.textContent = '';
  renderModelsStatus();
}

// Мост отвечает мгновенно, локальный opencode — нет: показываем, что
// идёт ожидание, иначе пустая таблица выглядит как «моделей нет».
async function modelsAskAll() {
  const input = $('modelsAsk');
  const text = (input && input.value || '').trim();
  const msg = $('modelsMsg'), box = $('modelsBox');
  if (!text) {
    if (msg) msg.textContent = 'вопрос пустой';
    return;
  }
  if (modelsBusy) return;
  modelsBusy = true;
  if (msg) msg.textContent = 'спрашиваю все модели…';
  if (box) {
    box.hidden = false;
    box.innerHTML = '<div class="hintBlock">Жду ответы… Модели отвечают параллельно,'
      + ' но запрос у каждой занимает секунды, а отказавшиеся ждут таймаут.</div>';
  }
  const started = Date.now();
  const r = await api('/api/models/ask_all', {text: text, timeout: 180});
  modelsBusy = false;
  if (msg) msg.textContent = '';
  renderAskAll(r, Date.now() - started);
  // Статус после опроса обязательно перечитываем: он изменился.
  modelsStatus();
}

function renderModelsStatus() {
  const box = $('modelsBox');
  if (!box) return;
  const r = MODELS_STATE || {};
  const bridge = r.bridge || {};
  const local = r.local_llm || {};
  const rows = r.models || [];

  let head = '<div class="row tight mini dim">';
  head += `<span>мост ${bridge.ok ? 'отвечает' : 'не отвечает'}`;
  if (bridge.uptime_s) head += `, работает ${fmtLeft(bridge.uptime_s)}`;
  if (bridge.requests) head += `, запросов ${esc(bridge.requests)}, отказов ${esc(bridge.failures)}`;
  head += '</span>';
  head += `<span>Ollama ${local.running ? 'запущен' : 'выключен'}</span>`;
  if (bridge.error) head += `<span class="bad">${esc(bridge.error)}</span>`;
  if (local.error) head += `<span class="dim">${esc(local.error)}</span>`;
  head += '</div>';

  if (!rows.length) {
    // Пустая таблица — это тоже результат, и молчать о нём нельзя:
    // человек поймёт не «моделей нет», а «мост не поднят».
    box.innerHTML = head + '<div class="hintBlock">Моделей в таблице нет.'
      + ' Мост поднимается вместе с основным сервером (zagent.bat).'
      + (bridge.error ? ' Причина: ' + esc(bridge.error) : '') + '</div>';
    return;
  }

  let html = head + '<div class="modelsTable">';
  for (const row of rows) {
    const id = String(row.id || '');
    const reason = row.reason ? `<div class="mini dim">${esc(row.reason)}</div>` : '';
    const cooling = row.cooldown_left_s > 0
      ? `<span class="mini dim"> ещё ${esc(fmtLeft(row.cooldown_left_s))}</span>` : '';
    const ms = row.last_ms ? `<span class="mini dim">${esc(row.last_ms)} мс</span>` : '';
    html += `<div class="modelsRow">`
      + `<div class="modelsName" title="${esc(id)}">${esc(id)}</div>`
      + `<div>${modelStateMark(row.state)}${cooling} ${ms}`
      + `<span class="mini dim"> ${esc(row.source || row.provider || '')}</span></div>`
      + `${reason}</div>`;
  }
  html += '</div>';
  box.innerHTML = html;
}

function renderAskAll(r, waited_ms) {
  const box = $('modelsBox');
  if (!box) return;
  if (!r || r.ok === false) {
    box.innerHTML = '<div class="hintBlock bad">'
      + esc((r && r.error) || 'мост не ответил') + '</div>';
    return;
  }
  const results = r.results || [];
  if (!results.length) {
    box.innerHTML = '<div class="hintBlock">Мост не вернул ни одной строки.'
      + ' Проверьте, что он поднят.</div>';
    return;
  }
  let html = '<div class="hintBlock">Ответили ' + esc(r.answered || 0) + ' из '
    + esc(r.asked || 0) + ' за ' + esc(Math.round((r.duration_ms || waited_ms) / 100) / 10)
    + ' с</div><div class="modelsTable">';
  for (const item of results) {
    const ok = item.ok;
    html += `<div class="modelsRow">`
      + `<div class="modelsName" title="${esc(item.id || '')}">${esc(item.id || '')}</div>`
      + `<div>${ok ? '<span class="chip ok">ответила</span>' : '<span class="chip bad">отказ</span>'}`
      + ` <span class="mini dim">${esc(item.ms || 0)} мс${item.via ? ' · ' + esc(item.via) : ''}</span></div>`
      + `<div class="mini">${esc(ok ? (item.answer || '') : (item.error || ''))}</div>`
      + '</div>';
  }
  html += '</div>';
  box.innerHTML = html;
}

async function loadDev(force) {
  if (!DEV || !DEV.ok || force) DEV = await api('/api/dev');
  renderDev();
}

function renderDev() {
  const btn = $('devBtn'), box = $('devBox'), msg = $('devMsg');
  if (!btn || !DEV || !DEV.ok) {
    if (msg) msg.textContent = (DEV && DEV.error) || 'нет данных от сервера';
    if (box) box.hidden = true;
    return;
  }
  btn.textContent = DEV.on ? 'Выключить' : 'Включить';
  btn.className = 'btn sm ' + (DEV.on ? '' : 'pri');
  if (msg) msg.textContent = DEV.on
    ? 'включён · диагностика обновляется кнопкой «Обновить»'
    : 'выключен · нажмите, чтобы увидеть диагностику';

  if (!DEV.on) { box.hidden = true; return; }
  box.hidden = false;
  const err = DEV.errors || {};
  // Порядок строк — от «где я нахожусь» к «что сломалось»: путь читают
  // чаще всего, ошибку ищут в конце. Число ошибок в журнале стоит сразу
  // после пути: это самый часто читаемый показатель, и человек должен
  // видеть его, не нажимая ничего.
  const rows = [
    ['проект', DEV.root],
    ['база', DEV.db],
    ['ошибок в журнале', `${err.count ?? 0}${err.lost ? ` (+${err.lost} потеряно)` : ''}`],
    ['файл журнала', err.path || '—'],
    ['Python', DEV.python],
    ['моделей в реестре', DEV.models],
    ['задач в базе', DEV.tasks],
    ['событий в базе', DEV.events],
    ['последняя ошибка', DEV.last_error || 'нет'],
  ];
  box.innerHTML = '<dl class="kv">' + rows.map(([k, v]) =>
    `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('') + '</dl>';
}

// Журнал ошибок: что программа проглотила. Показываем не всё, а последние
// записи с местом и текстом: длинный список на экране не читается, а
// полный файл всегда можно скачать кнопкой ниже.
let DIAG = null;

async function diagShow() {
  DIAG = await api('/api/diag');
  renderDiag();
}

function renderDiag() {
  const box = $('diagBox');
  if (!box || !DIAG || !DIAG.ok) {
    if (box) box.textContent = (DIAG && DIAG.error) || 'нет данных от сервера';
    return;
  }
  box.hidden = false;
  const rows = DIAG.recent || [];
  const head = `<div class="row tight" style="padding:4px 0">
      <span class="mini dim">всего записей: ${DIAG.count || 0}${
        DIAG.lost ? ` · потеряно: ${DIAG.lost}` : ''}</span>
      <a class="btn sm" href="/api/diag?download=1" download>Скачать .jsonl</a>
    </div>`;
  if (!rows.length) {
    box.innerHTML = head + '<div class="mini dim">Журнал пуст — ошибок не было.</div>';
    return;
  }
  const body = rows.map(r => {
    const when = r.at ? new Date(r.at * 1000).toLocaleTimeString() : '';
    const what = r.error || r.msg || '';
    return `<div class="mini" style="padding:2px 0;border-bottom:1px solid var(--dim)">
        <b>${esc(r.scope || '?')}</b> <span class="dim">${esc(when)}</span><br>
        ${esc(what)}${r.trace ? '<br><span class="dim">(трейс есть в файле)</span>' : ''}
      </div>`;
  }).join('');
  box.innerHTML = head + body;
}

async function diagClear() {
  // Подтверждение обязательно: журнал — единственный след сбоя, а кнопка
  // стоит рядом с «Обновить» и выглядит безобидно.
  const yes = await askYes('Очистить журнал ошибок?',
    'Все записи будут удалены безвозвратно. Файл можно скачать кнопкой выше.');
  if (!yes) return;
  const r = await api('/api/diag', {clear: true});
  if (!r.ok) { toast(r.error || 'ошибка сервера'); return; }
  DIAG = r;
  renderDiag();
  await loadDev(true);
  toast('журнал очищен');
}

// Переключение режима. Ответ содержит и флаг, и диагностику, поэтому
// второй запрос за состоянием не нужен: один ответ — и кнопка, и панель
// показывают правду.
async function devToggle() {
  const next = !(DEV && DEV.on);
  const r = await api('/api/dev', {on: next});
  if (!r.ok) { setNote('devMsg', r.error || 'ошибка сервера', false); return; }
  DEV = r;
  renderDev();
  toast(next ? 'Режим разработчика включён' : 'Режим разработчика выключен');
}

async function devRefresh() {
  await loadDev(true);
  if (DEV && DEV.ok && !DEV.on) setNote('devMsg',
    'режим выключен — включите его, чтобы увидеть диагностику', false);
  else toast('диагностика обновлена');
}

async function loadSettings(force) {
  if (!SETTINGS || !SETTINGS.ok || force) SETTINGS = await api('/api/settings');
  await loadDev();
  renderSettings();
  if (!SETTINGS || !SETTINGS.ok) {
    setNote('keyMsg', (SETTINGS && SETTINGS.error) || 'нет данных от сервера', false);
  }
}

function settingsGateways() {
  return (SETTINGS && SETTINGS.ok) ? (SETTINGS.gateways || []) : [];
}

function pickGateway(selId) {
  const list = settingsGateways();
  const box = $(selId);
  if (!box || !list.length) return null;
  return list.find(g => g.id === box.value) || list[0];
}

function fillGatewaySelects() {
  const list = settingsGateways();
  if (!list.length) return;
  const opts = list.map(g =>
    `<option value="${esc(g.id)}">${esc(g.label)}${g.needs_key ? '' : ' · без ключа'}</option>`
  ).join('');
  for (const id of ['keyGw', 'modGw']) {
    const box = $(id);
    if (!box) continue;
    const keep = box.value;
    box.innerHTML = opts;
    if (keep && list.some(g => g.id === keep)) box.value = keep;
  }
}

function renderSettings() {
  fillGatewaySelects();
  renderKeySide();
  renderModelList();
}

// Строка состояния шлюза плюс доп. поля: у Cloudflare второй секрет —
// Account ID, он лежит в {placeholder} внутри base_url.
function renderKeySide() {
  const g = pickGateway('keyGw');
  const info = $('keyInfo'), extra = $('keyExtra'), text = $('keyText');
  if (!g) { info.textContent = 'нет данных'; extra.innerHTML = ''; return; }

  // Четыре честных состояния: поле для ввода, встроенный литерал (Ollama),
  // ключ только из переменной окружения, и шлюз без ключа вовсе. Раньше
  // все четыре выглядели как «поле: — · ключей: 1», и человек не понимал,
  // куда вообще вставлять.
  if (g.key_field) {
    info.textContent = `поле: ${g.key_field} · ключей: ${g.key_count}` +
      (g.from_env ? ` · задан переменной ${g.env_var}, файл не используется` : '');
    text.disabled = false;
    text.placeholder = 'по одному ключу в строке';
  } else if (g.literal) {
    info.textContent = 'Ключ не нужен — шлюз использует встроенный литерал';
    text.disabled = true;
    text.placeholder = 'вводить нечего';
  } else if (g.needs_key) {
    info.textContent = 'Ключ задаётся переменной окружения — поля в файле нет';
    text.disabled = true;
    text.placeholder = 'вводить нечего';
  } else {
    info.textContent = 'Ключ не нужен — шлюз работает без него';
    text.disabled = true;
    text.placeholder = 'для этого шлюза ключи не нужны';
  }

  extra.innerHTML = (g.extra_fields || []).map(f => `
    <div class="field">
      <label>${esc(f.label)} — одиночное значение</label>
      <div class="row tight" style="padding:0 0 6px">
        <input data-x="${esc(f.name)}" spellcheck="false" style="flex:1"
               placeholder="${esc(f.name)}">
        <button class="btn sm" data-name="${esc(f.name)}"
                onclick="extraSave(this)">Сохранить</button>
      </div>
    </div>`).join('');
}

function setNote(id, text, ok) {
  const box = $(id);
  if (!box) return;
  box.textContent = (ok ? '' : '⚠ ') + text;
}

function keysSummary(r) {
  if (r.action === 'add') {
    return `добавлено ${r.added} из ${r.added + r.duplicates} · всего ${r.total}`;
  }
  if (r.action === 'replace') return `заменено: теперь ${r.total} (было ${r.was})`;
  return `удалено ${r.removed} · осталось ${r.total}`;
}

async function keysSend(action) {
  const g = pickGateway('keyGw');
  if (!g || !g.key_field) {
    setNote('keyMsg', 'у этого шлюза нет поля для ключа', false);
    return;
  }
  if (action === 'replace') {
    const yes = await askYes('Заменить все ключи?',
      `Шлюз «${g.label}»: сейчас ${g.key_count} ключ(ей). ` +
      'Вставленные строки затрут список целиком.');
    if (!yes) return;
  }
  const r = await api('/api/keys', {name: g.key_field, keys: $('keyText').value, action});
  setNote('keyMsg', r.ok ? keysSummary(r) : (r.error || 'ошибка сервера'), r.ok);
  if (r.ok) {
    $('keyText').value = '';
    await loadSettings(true);
    if (r.scan) toast(`Каталог пересобран: ${r.scan.models ?? 0} моделей`);
  }
}

// Сохранение одиночного значения (Account ID у Cloudflare): replace + single,
// иначе сервер сложил бы поле в список, а список в base_url подставить нельзя.
async function extraSave(btn) {
  const name = btn.dataset.name;
  const input = document.querySelector(`input[data-x="${name}"]`);
  if (!input || !input.value.trim()) { setNote('keyMsg', 'значение пустое', false); return; }
  const r = await api('/api/keys', {
    name, keys: input.value.trim(), action: 'replace', single: true,
  });
  setNote('keyMsg', r.ok ? `${name}: сохранено` : (r.error || 'ошибка сервера'), r.ok);
  if (r.ok) { input.value = ''; await loadSettings(true); }
}

function renderModelList() {
  const g = pickGateway('modGw');
  const box = $('modList');
  if (!box) return;
  if (!g) { box.innerHTML = ''; return; }
  const models = g.free_models || [];
  const catalog = (g.catalog || []).join(' + ') || 'статический';
  const mono = 'font-family:var(--mono);font-size:11.5px';
  box.innerHTML = `<div class="mini dim" style="padding:2px 10px">
      Ручные модели: ${esc(g.label)} · каталог ${esc(catalog)}</div>` +
    (models.length
      ? models.map(m => `<div class="row tight">
          <span style="flex:1;${mono}">${esc(m)}</span>
          <button class="btn sm" data-gw="${esc(g.id)}" data-model="${esc(m)}"
                  onclick="modelDrop(this)">убрать</button></div>`).join('')
      : `<div class="mini dim" style="padding:0 10px 8px">Пока пусто.</div>`);
}

async function modelDrop(btn) {
  const m = btn.dataset.model, gw = btn.dataset.gw;
  const yes = await askYes('Убрать модель?',
    `${m} · шлюз ${gw}: уйдёт из каталога и из tiers.json.`);
  if (!yes) return;
  const r = await api('/api/models', {gateway: gw, model: m, action: 'remove'});
  setNote('modMsg', r.ok ? `удалена: ${m}` : (r.error || 'ошибка сервера'), r.ok);
  if (r.ok) await loadSettings(true);
}

async function modelSend(action) {
  const g = pickGateway('modGw');
  const id = (($('modId') || {}).value || '').trim();
  if (!g) return;
  if (!id) { setNote('modMsg', 'впишите идентификатор модели', false); return; }
  const tier = +$('modTier').value;
  const notes = (($('modNote') || {}).value || '').trim();
  const r = await api('/api/models', {gateway: g.id, model: id, action, tier, notes});
  setNote('modMsg', r.ok
    ? (action === 'add' ? `добавлена: ${id} · тир ${tier}` : `удалена: ${id}`)
    : (r.error || 'ошибка сервера'), r.ok);
  if (r.ok) {
    if (action === 'add') { $('modId').value = ''; $('modNote').value = ''; }
    await loadSettings(true);
  }
}

// Полный ключ, а не маска. Сервер отдаёт ключи замаскированными
// (`mask_secret()` в connect.py), и копировалась именно маска: в буфер
// попадало `sk-or…a1b2`, а тост рапортовал об успехе. Полный ключ
// запрашивается отдельным действием (`reveal_key`) именно для такого
// случая, и раньше из интерфейса оно не вызывалось вовсе.
async function copyKey(gw) {
  try {
    const r = await api('/api/connect', {reveal_key: true, gateway: gw});
    // Сервер на ошибку отдаёт `ok: false`, а не `error`: иначе молчаливое
    // «ключ не показан» выглядело бы как успешное копирование.
    if (!r.ok || r.error) {
      toast('Не получилось показать ключ: ' + (r.error || 'неизвестная причина'));
      return;
    }
    const key = r.api_key || '';
    if (!key || key.includes('\u2026')) {
      toast('Сервер вернул замаскированный ключ \u2014 скопировать нечего.');
      return;
    }
    copy(key, 'api key ' + gw);
  } catch (e) {
    toast('Не получилось показать ключ: ' + (e && e.message ? e.message : e));
  }
}

// ---------- темы ----------
// Тема хранится в localStorage и применяется до первой отрисовки (см.
// инлайн-скрипт в <head>), иначе при загрузке моргает исходная тема.
const THEMES = ['dark','black','light','blue','gray'];
function setTheme(name) {
  if (!THEMES.includes(name)) return;
  document.documentElement.dataset.theme = name;
  // Пишем обычной строкой. Раньше здесь был JSON.parse при чтении,
  // а запись была без кавычек: JSON.parse('dark') падал, исключение
  // глоталось, и выбор темы молча терялся при каждом F5.
  try { localStorage.setItem('zagent.theme', name); } catch {}
  document.querySelectorAll('.themeDot').forEach(d =>
    d.classList.toggle('on', d.dataset.t === name));
}
function initTheme() {
  let saved = null;
  try {
    const raw = localStorage.getItem('zagent.theme');
    // Значение — простая строка, а не JSON: проверяем по списку
    // тем, иначе в localStorage может лежать что угодно.
    saved = THEMES.includes(raw) ? raw : null;
  } catch {}
  // При первом запуске берём тему системы: ночью тёмная, днём светлая.
  if (!saved && window.matchMedia) {
    saved = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  setTheme(THEMES.includes(saved) ? saved : 'dark');
}

// ---------- доступность из России ----------
const RU_MARKS = {
  ok:      ['✔', 'доступна из России без VPN'],
  vpn:     ['🔒', 'из России работает только с VPN'],
  blocked: ['✘', 'недоступна даже с VPN'],
  unknown: ['?', 'не проверено из России'],
};
function ruBadge(r) {
  const st = (r.region && r.region.status) || 'unknown';
  const [mark, tip] = RU_MARKS[st] || RU_MARKS.unknown;
  return `<span class="ru ru-${st}" title="${esc(tip)}">РФ ${mark}</span>`;
}

// Панель замера: кнопка, просит выключить/включить VPN, прогресс и итог.
// Рисуется в раскрывающемся блоке, а не в списке моделей.
function geoPanel() {
  const rs = (S && S.regions) || {counts:{}, measured:0};
  const g = GEO.running ? GEO.progress : null;
  const c = rs.counts || {};
  const left = Math.max(0, (g ? g.total : 0) - (g ? g.done : 0));
  const pct = g && g.total ? Math.round(g.done * 100 / g.total) : 0;
  const measured = rs.measured || 0;

  // Пока идёт замер, панель поднимают: иначе прогресс не видно, а он идёт
  // несколько минут.
  if (g) openFold('fGeo');

  let head = '';
  if (g) {
    head = `<div class="geoStep">Замер идёт: <b>${esc(g.phase || 'проверка')}</b></div>
      <div class="barTrack"><div class="barFill" style="width:${pct}%"></div></div>
      <div class="geoStat">
        <span>${g.done} из ${g.total}</span>
        <span>осталось ${left}</span>
        <span class="dim">${esc(g.current || '')}</span>
      </div>`;
  } else if (rs.measured) {
    head = `<div class="geoStep">Проверено моделей: <b>${measured}</b></div>`;
  } else {
    head = `<div class="geoStep">Доступность из России ещё не проверена.</div>`;
  }

  const sum = `<div class="geoSum">
      <span class="ru ru-ok">РФ ✔ ${c.ok||0}</span>
      <span class="ru ru-vpn">РФ 🔒 ${c.vpn||0}</span>
      <span class="ru ru-blocked">РФ ✘ ${c.blocked||0}</span>
      <span class="ru ru-unknown">РФ ? ${c.unknown||0}</span>
    </div>`;

  // Подсказка ведёт по шагам: сначала выключить VPN, потом включить. Второй
  // замер без первого бесполезен, поэтому он выделен.
  const needDirect = !GEO.directDone;
  const steps = `
    <div class="geoSteps">
      <div class="geoStepRow ${needDirect ? 'now' : 'done'}">
        <span class="n">${needDirect ? '1' : '✓'}</span>
        <span class="tx">${needDirect
          ? '<b>Выключите VPN</b> и нажмите «Замер без VPN»'
          : 'Замер без VPN сделан'}</span>
        <button class="btn sm pri" onclick="geo('direct')"
                ${GEO.running ? 'disabled' : ''}>Замер без VPN</button>
      </div>
      ${needDirect ? `<div class="geoWarn">Замер «без VPN» записывает вывод
        «работает из России». Если VPN останется включённым, данные будут
        неверными: почти всё ответит и метки станут ✔. Проверьте, что VPN
        действительно выключен.</div>` : ''}
      <div class="geoStepRow ${!needDirect ? 'now' : ''}">
        <span class="n">2</span>
        <span class="tx">${needDirect
          ? 'Затем включите VPN и повторите'
          : '<b>Включите VPN</b> и нажмите «Замер с VPN»'}</span>
        <button class="btn sm" onclick="geo('vpn')"
                ${GEO.running || needDirect ? 'disabled' : ''}>Замер с VPN</button>
      </div>
    </div>`;

  const hint = `<div class="geoHint">С включённым VPN отвечает почти всё, поэтому один
    такой замер ничего не доказывает. Вывод «работает без VPN» ставится только
    по первому замеру, и он не стирается вторым.</div>`;

  const log = (GEO.log && GEO.log.length)
    ? `<div class="geoLog">${GEO.log.slice(-6).map(l =>
        `<div>${esc(l)}</div>`).join('')}</div>`
    : '';

  return `<div class="geoBox">${head}${sum}${steps}${hint}${log}</div>`;
}

async function geo(mode) {
  if (GEO.running) return;
  // Страховка от самой частой ошибки: замер «без VPN» при включённом VPN
  // записывает ложное «доступно из России» и портит вердикт до конца сессии.
  if (mode === 'direct') {
    const sure = await askYes('Точно выключили VPN?',
      'Этот замер запишет вывод «работает из России».\n\n' +
      'Если VPN останется включённым, данные будут неверными.');
    if (!sure) return;
  }
  GEO.running = true;
  GEO.progress = {done:0, total:0, current:'', phase:'старт'};
  GEO.log = [];
  renderModels();
  const r = await api('/api/region', {action:'measure', mode});
  if (!r.ok) { toast(r.error || 'не вышло'); GEO.running = false; refresh(); return; }
  toast(mode === 'direct' ? 'Замер без VPN запущен' : 'Замер с VPN запущен');
  refresh();
}

function renderVpnNote() {
  const rs = (S && S.regions) || {counts:{}, measured:0};
  const c = rs.counts || {};
  const box = $('vpnNote');
  if (!box) return;
  box.innerHTML = rs.measured
    ? `Проверено ${rs.measured}: без VPN ${c.ok||0}, нужен VPN ${c.vpn||0}, ` +
      `недоступно ${c.blocked||0}. При «сначала без VPN» модели, которым VPN необходим, ` +
      `опускаются в конец списка, но остаются доступны — вдруг VPN включится.`
    : `Нажмите «Замер без VPN» при выключенном VPN, затем «Замер с VPN» при включённом. ` +
      `Один замер с VPN ничего не доказывает.`;
}

// ---------- инструкции по подключению ----------
async function loadGuide(target) {
  const box = $('guideBox');
  box.innerHTML = '<div class="mini dim" style="padding:6px 0">загрузка…</div>';
  const r = await api('/api/connect', {target});
  if (!r.ok) { box.innerHTML = '<div class="warnbox">' + esc(r.error) + '</div>'; return; }
  GUIDE = r;

  let html = '';
  const usable = (r.entries || []).filter(e => e.available);
  const blocked = (r.entries || []).filter(e => !e.available);

  for (const e of usable) {
    html += `<div class="mgroup">
      <h4>${esc(e.label)}</h4>
      <dl class="kv">
        <dt>provider</dt><dd class="copy" onclick="copy('${jsq(e.provider_id)}','provider id')">${esc(e.provider_id)}</dd>
        <dt>base URL</dt><dd class="copy" onclick="copy('${jsq(e.base_url)}','base URL')">${esc(e.base_url)}</dd>
        ${e.keyless ? '' : `<dt>api key</dt><dd class="copy" onclick="copyKey('${jsq(e.gateway)}')">${
            e.api_key ? esc(e.api_key.slice(0,10)) + '…' + esc(e.api_key.slice(-4))
                      : '<span class="dim">—</span>'}</dd>`}
      </dl>
      <pre>${esc(e.instruction)}</pre>
      <div class="row tight" style="padding:0 10px 8px">
        <button class="btn sm pri" data-copy="${esc(e.instruction)}" onclick="copyAttr(this,'инструкция')">копировать</button>
        <button class="btn sm" onclick="copyModels('${jsq(e.gateway)}')">только модели</button>
      </div>
    </div>`;
  }
  if (blocked.length) {
    html += '<div class="warnbox"><b>Не подключаются:</b><br>' +
      blocked.map(e => esc(e.label) + ' — ' + esc(e.reason)).join('<br>') + '</div>';
  }
  if (!usable.length) html += '<div class="empty">Нет доступных шлюзов</div>';
  box.innerHTML = html;
}
function copyModels(gw) {
  const c = (GUIDE?.connections || []).find(x => x.gateway === gw);
  copy((c?.models || []).join('\n'), 'список моделей');
}

// ---------- \u0444\u0430\u0439\u043b\u044b ----------
// \u041f\u0430\u043d\u0435\u043b\u044c \u0441\u043f\u0440\u0430\u0432\u0430 \u0441\u043b\u0443\u0436\u0438\u0442 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u043e\u043c \u043f\u043e \u043f\u0430\u0442\u0438: \u0445\u043b\u0435\u0431\u043d\u044b\u0439, \u0434\u043e\u0432\u043e\u0434\u044b, \u043f\u0430\u043f\u043a\u0430 \u0438
// \u0438\u0441\u0442\u043e\u0440\u0438\u044f \u043f\u0435\u0440\u0435\u0445\u043e\u0434\u0430 \u043f\u043e \u0432\u043b\u0430\u0434\u0435\u043b\u044c\u0446\u0430\u043c. \u0410\u043d\u0435\u0442\u0430\u0446\u0438\u044f \u0442\u0430\u043a\u0436\u0435: \u0441\u043f\u0438\u0441\u043e\u043a
// \u0434\u043e \u043a\u043e\u043d\u0446\u0430 \u043e\u0441\u0442\u0430\u043b\u0441\u044f \u043f\u043e\u0441\u043b\u0435 \u0432\u044b\u0431\u043e\u0440\u0430 \u043c\u043e\u0434\u0435\u043b\u0438 \u2014 \u0440\u0430\u0437 \u0443\u0432\u0435\u043b\u0438\u0447\u0438\u0432\u0430\u0435\u0442 \u0441\u0442\u0440\u043e\u043a\u0443
// \u043a \u0448\u0430\u0433\u043e\u043c \u043d\u0430 \u0441\u0435\u043b\u0435\u043a\u0442 \u0435\u0435 \u0438\u0434\u0435\u043d\u0442\u0438\u0447\u043d\u043e\u0441\u0442\u0438.
let fCur = '.', fFile = null, fWeb = '';

async function loadTree(path) {
  fCur = path || '.';
  const r = await api('/api/files', {path: fCur});
  if (!r.ok) { $('ftree').innerHTML = '<div class="empty">' + esc(r.error) + '</div>'; return; }
  fWeb = r.web_root || '';
  if (r.kind === 'file') { showFile(r); return; }

  $('fsPath').textContent = r.path === '.' ? '\u043a\u043e\u0440\u0435\u043d\u044c' : r.path;
  renderCrumbs(r.path);

  const icons = {dir:'\u25b8', image:'\ud83d\udcbe', text:'\u00b7', binary:'\u25a1'};
  let html = '';
  if (r.path !== '.') {
    html += `<div class="fitem" onclick="loadTree('${jsq(parentOf(r.path))}')">
      <span class="ic">\u2191</span><span class="nm">\u043d\u0430\u0437\u0430\u0434</span></div>`;
  }
  for (const e of r.entries) {
    const full = (r.path === '.' ? '' : r.path + '/') + e.name;
    const isDir = e.is_dir ?? (e.type === 'dir');
    const kind = isDir ? 'dir' : (e.type || 'text');
    // Правый клик открывает «системное» меню, где есть «открыть в
    // браузере». Само по себе `file:///` в href не годится: браузер
    // запрещает такие переходы из страницы, а без ссылки открыть
    // результат из дерева нечем.
    html += `<div class="fitem${fFile === full ? ' on' : ''}"
                 oncontextmenu="fileMenu(event, '${esc(full)}', ${isDir})"
                 onclick="openEntry('${jsq(full)}',${isDir})"
                 title="${esc(full)}">
      <span class="ic">${isDir ? '\u25b8' : (icons[kind] || '\u00b7')}</span>
      <span class="nm">${esc(e.name)}</span>
      ${e.size ? `<span class="sz">${fmtSize(e.size)}</span>` : ''}
    </div>`;
  }
  $('ftree').innerHTML = html || '<div class="empty">\u043f\u0430\u043f\u043a\u0430 \u043f\u0443\u0441\u0442\u0430</div>';
}

// Меню правого клика по файлу в дереве.
//
// Раньше результат работы агента можно было посмотреть только глазами в
// панели справа: в самом ответе был текст со списком имён. Теперь у файла
// есть «открыть в браузере», и для страниц это единственный способ увидеть
// результат таким, каким его увидит человек.
function fileMenu(ev, path, isDir) {
  ev.preventDefault();
  ev.stopPropagation();
  hideFileMenu();

  const menu = document.createElement('div');
  menu.id = 'fileMenu';
  menu.className = 'ctxmenu';
  menu.style.left = Math.min(ev.clientX, window.innerWidth - 210) + 'px';
  menu.style.top = Math.min(ev.clientY, window.innerHeight - 120) + 'px';

  const items = [{label: 'Показать здесь', fn: () => openEntry(path, isDir)}];
  if (!isDir) {
    items.push({label: 'Скопировать путь', fn: () => copy(path, 'путь')});
  }
  menu.innerHTML = items.map((it, i) =>
    `<div class="ctxitem" data-i="${i}">${esc(it.label)}</div>`).join('');
  menu.addEventListener('click', (ev2) => {
    const row = ev2.target.closest('.ctxitem');
    if (!row) return;
    items[Number(row.dataset.i)].fn();
    hideFileMenu();
  });

  document.body.appendChild(menu);
  setTimeout(() => document.addEventListener('click', hideFileMenu, {once: true}), 0);
}

function hideFileMenu() {
  document.getElementById('fileMenu')?.remove();
}

// \u0425\u043b\u0435\u0431\u044b: \u043f\u043e\u043a\u0430\u0437\u0430\u043d\u043e, \u0433\u0434\u0435 \u0432\u044b \u0441\u0438\u043c\u0435\u043d\u044c. \u0411\u0435\u0437 \u043d\u0438\u0445 \u043d\u0430\u0437\u0430\u0434 \u00ab\u2039\u203a\u00bb \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442
// \u0442\u043e\u043b\u044c\u043a\u043e \u043d\u0430 \u043a\u043e\u0440\u043d\u044c, \u0430 \u0434\u043b\u0438\u043d\u043d\u0430\u044f \u043f\u0443\u0442\u044c \u043d\u0435 \u043e\u0442\u043a\u0440\u044b\u0432\u0430\u0435\u0442\u0441\u044f.
function renderCrumbs(path) {
  const parts = (path === '.' ? [] : path.split('/').filter(Boolean));
  let html = `<span class="crumb" onclick="loadTree('.')">\u041a\u043e\u0440\u0435\u043d\u044c</span>`;
  let acc = '';
  parts.forEach((part, i) => {
    acc += (acc ? '/' : '') + part;
    const target = acc;
    const last = i === parts.length - 1;
    html += `<span class="sep">/</span><span class="crumb${last ? ' on' : ''}"
             onclick="loadTree('${jsq(target)}')">${esc(part)}</span>`;
  });
  $('fcrumbs').innerHTML = html;
}

function parentOf(p) {
  const parts = p.split('/').filter(Boolean);
  parts.pop();
  return parts.join('/') || '.';
}
function openEntry(path, isDir) { if (isDir) loadTree(path); else openFile(path); }

async function openFile(path) {
  fFile = path;
  // \u041e\u0442\u043c\u0435\u0447\u0430\u0435\u043c \u043f\u043e\u0434\u0441\u0432\u0435\u0442\u043a\u0443 \u0432 \u0434\u0435\u0440\u0435\u0432\u0435: \u0438\u043d\u0430\u0447\u0435 \u043f\u0440\u0438 \u043a\u043b\u0438\u043a\u0435
  // \u043f\u043e \u0441\u0442\u0430\u0440\u044b\u043c \u0444\u0430\u0439\u043b\u0430\u043c \u043c\u043e\u0433\u043b\u0430 \u0431\u044b \u0443\u0432\u0435\u0434\u0435\u043d\u043e \u043d\u0435 \u0442\u0430\u043c.
  loadTree(fCur);

  const r = await api('/api/files', {path});
  if (!r.ok) { $('fview').innerHTML = '<div class="empty">' + esc(r.error) + '</div>'; return; }
  showFile(r);
}

// \u041f\u0440\u043e\u0441\u043c\u043e\u0442\u0440 \u0444\u0430\u0439\u043b\u0430: \u043a\u0430\u0440\u0442\u0438\u043d\u043a\u0430 \u0440\u0438\u0441\u0443\u0435\u0442\u0441\u044f \u0432 \u043e\u043a\u043d\u0435 \u043f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043d\u044b\u0435,
// \u0438\u043d\u0430\u0447\u0435 \u0434\u043b\u044f \u043a\u0430\u0436\u0434\u043e\u0433\u043e \u0432\u044b\u0431\u043e\u0440\u0430 \u0441\u043e\u0437\u0434\u0430\u0442\u044c \u0437\u0430\u043d\u044f\u0442\u0438\u0435 \u043d\u0435 \u0432\u0443\u0439\u0434\u0435\u0442 \u0432 \u0444\u0430\u0439\u043b.
function showFile(r) {
  const head = `<div class="fhead">
      <span class="fn">${esc(r.path)}</span>
      <span class="dim mini">${r.lines ? r.lines + ' \u0441\u0442\u0440' : fmtSize(r.size || 0)}</span>
      <div class="spacer"></div>
      ${r.web_url ? `<a class="btn sm" href="${esc(r.web_url)}" target="_blank"
         rel="noopener" title="\u043e\u0442\u043a\u0440\u044b\u0442\u044c \u0432 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0435 \u0432\u043e \u0432\u043d\u0443\u0442\u0440\u0435\u043d\u043d\u0435\u043c \u0432\u043a\u043b\u0430\u0434\u043a\u0435">\u2197</a>` : ''}
      <button class="btn sm" data-copy="${esc(r.content || r.data_url || '')}" onclick="copyAttr(this,'\u0441\u043e\u0434\u0435\u0440\u0436\u0438\u043c\u043e\u0435')">\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c</button>
    </div>`;

  if (r.kind === 'image') {
    $('fview').innerHTML = head +
      `<div class="imgWrap"><img src="${r.data_url}" alt="${esc(r.path)}"></div>`;
    return;
  }
  if (r.kind === 'binary') {
    $('fview').innerHTML = head +
      `<div class="empty">${esc(r.note || 'показать нечем')}</div>`;
    return;
  }
  const lang = r.language ? ` data-lang="${esc(r.language)}"` : '';
  $('fview').innerHTML = head +
    `<pre class="code"${lang}>${esc(r.content)}${r.truncated ? '\n\n\u2026 \u043e\u0431\u0440\u0435\u0437\u0430\u043d\u043e' : ''}</pre>`;
}

function fmtSize(n) {
  if (!n) return '0 B';
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n/1024).toFixed(1) + ' K';
  return (n/1048576).toFixed(1) + ' M';
}

// ---------- отправка ----------
async function send() {
  const box = $('cbox');
  const text = box.value.trim();
  if (!text) return;
  box.value = '';
  addMsg({who:'вы', text:text, kind:'user'});

  const body = {task: text, plan_only: $('planChk').checked,
                workspace_id: $('wsSel').value,
                // Режимы работы. По умолчанию «Авто»: решение о поиске и
                // разбиении принимает программа и объясняет его. Ручные
                // флаги приходят только когда человек выбрал режим сам.
                auto_mode: TASK_FLAGS.auto,
                subagents: TASK_FLAGS.subagents,
                web_research: TASK_FLAGS.research,
                herd: TASK_FLAGS.herd,
                self_edit: TASK_FLAGS.selfdev};
  if (ATTACH.length) body.images = ATTACH.map(a => ({data_url: a.url, name: a.name}));
  $('sendInfo').textContent = 'ставлю в очередь…';
  const r = await api('/api/tasks', body);
  $('sendInfo').textContent = '';
  if (!r.ok) {
    // Текст не принят — возвращаем его в поле. Раньше он исчезал
    // вместе с очисткой и не оставался нигде.
    box.value = text;
    toast('Ошибка: ' + r.error); return;
  }
  curTask = r.task_id;
  $('stopBtn').style.display = '';
  // Вложения уходят в задачу и возвращаются в исходное состояние.
  // Раньше список не очищался, и каждая следующая задача молча
  // переотправляла картинки предыдущей. Чистим только здесь:
  // выше по коду стоит ранний выход при ошибке сервера, и тогда
  // вложения у человека остаются.
  ATTACH = [];
  renderAttachments();
  refresh();
}
async function stopTask() {
  if (!curTask) return;
  await api('/api/tasks/cancel', {task_id: curTask});
  toast('Запрошена отмена');
}
async function askOne(ref) {
  // Быстрый запрос к конкретной модели: переключаем режим и спрашиваем.
  await api('/api/mode', {mode:'manual', manual_ref: ref});
  addMsg({who:'вы', text:`→ ${ref}`, kind:'sys'});
  refresh();
}

// ---------- вложения ----------
async function addFiles(list) {
  for (const f of list) {
    if (!f.type.startsWith('image/')) continue;
    const url = await new Promise(res => {
      const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(f);
    });
    ATTACH.push({name: f.name, url});
  }
  renderAttachments();
  refresh(); // подтянуть vision-модели, если галочка стоит
}
async function takeShot() {
  $('sendInfo').textContent = 'снимаю экран…';
  const r = await api('/api/shot', {});
  $('sendInfo').textContent = '';
  if (!r.ok) { toast('Скриншот не сработал: ' + r.error); return; }
  ATTACH.push({name:'экран.png', url:r.data_url});
  renderAttachments();
  toast('Скриншот приложен');
}
function renderAttachments() {
  $('attach').innerHTML = ATTACH.map((a,i) =>
    `<div class="att"><img src="${a.url}" alt=""><span>${esc(a.name)}</span>
     <span class="x" onclick="ATTACH.splice(${i},1);renderAttachments()">✕</span></div>`
  ).join('');
}

// ---------- очередь ----------
function renderTasks() {
  const tasks = S.tasks || [];
  const counts = S.task_counts || {};
  $('chatInfo').textContent =
    `очередь ${counts.queued||0} · выполняется ${counts.running||0}`;

  if (!tasks.length) {
    $('taskList').innerHTML = '<div class="empty">Задач пока нет</div>';
    return;
  }
  let html = '';
  for (const t of tasks) {
    const can = ['queued','running','asking'].includes(t.status);
    html += `<div class="mgroup">
      <div class="row tight" style="padding:0 0 5px">
        <span class="dim mini">#${t.id}</span> ${chip(t.status)}
        <div style="flex:1"></div>
        ${can ? `<button class="btn sm danger" onclick="cancelTask(${t.id})">стоп</button>` : ''}
        ${t.status !== 'queued'
          ? `<button class="btn sm" onclick="blackBox(${t.id})">чёрный ящик</button>` : ''}
      </div>
      <div class="mini" style="padding:0">${esc((t.task||'').slice(0,90))}</div>
      ${t.status === 'asking' ? `<div class="row tight" style="padding:6px 0 0">
        <button class="btn sm pri" onclick="approveTask(${t.id})">одобрить план</button>
        <button class="btn sm" onclick="answerTask(${t.id})">ответить…</button>
      </div>` : ''}
    </div>`;
  }
  $('taskList').innerHTML = html;
}
async function cancelTask(id) { await api('/api/tasks/cancel', {task_id:id}); refresh(); }

// Чёрный ящик задачи: .jsonl с трейсом — хопы, модели, ошибки, токены.
// Скачивание, а не просмотр: файл открывают, когда задача уже кончилась,
// чтобы разобрать, почему она шла так, а не иначе.
function blackBox(id) { location.href = '/api/blackbox?task=' + id; }
async function approveTask(id) {
  await api('/api/tasks/answer', {task_id:id, approve:true, answer:''});
  refresh();
}
async function answerTask(id) {
  const text = await askText('Ответ агенту', '', {
    placeholder: 'например: бери папку src', okText: 'Отправить',
  });
  if (text === null || !String(text).trim()) return;
  await api('/api/tasks/answer', {task_id:id, answer:String(text)});
  refresh();
}

// ---------- папки работы ----------
async function switchWs(id) {
  const r = await api('/api/workspaces', {action:'activate', id});
  if (!r.ok) { toast(r.error || 'Не удалось переключить папку'); refresh(); return; }
  // После смены папки переписка тоже меняется: она принадлежит папке.
  await loadSession();
  refresh();
  const w = (r.workspaces || []).find(x => x.id === id);
  toast('Работаем в: ' + (w ? w.path : id));
}
async function wsAdd() {
  // Кнопка «выбрать папку». Отдельная функция, потому что выбор папки на
  // диске и ввод пути — разные вещи, и обе должны работать одинаково хорошо.
  const path = await askFolder('Папка для агента');
  if (!path || !String(path).trim()) return;
  const clean = String(path).trim().replace(/[\\/]+$/, '');

  // Папка с кодом zagent допустима — иногда правят сам софт, — но сказать
  // об этом надо до того, как агент в неё полезет.
  const code = ((S && S.workspaces) || {}).code_root || '';
  if (code && clean.toLowerCase().replace(/\//g, '\\')
      === code.toLowerCase().replace(/\//g, '\\')) {
    const yes = await askYes('Это папка самого zagent',
      clean + '\n\nВсё, что агент здесь создаст или изменит, попадёт в код '
      + 'программы. Для разработки софта это нужно, для обычной работы — нет.');
    if (!yes) return;
  }

  // Пробуем добавить, а если папки нет — предлагаем создать. Отказ с
  // объяснением лучше, чем «ничего не произошло».
  let r = await api('/api/workspaces', {action:'add', path: clean});
  if (!r.ok && /не найдена/i.test(r.error || '')) {
    const make = await askYes('Папки нет. Создать её?',
      clean + '\n\nАгент будет работать только внутри неё: всё, что он '
      + 'создаст, попадёт туда.');
    if (!make) { toast(r.error); return; }
    r = await api('/api/workspaces', {action:'create', path: clean});
  }
  if (!r.ok) { toast(r.error || 'Не удалось добавить папку'); refresh(); return; }

  // Переключаемся на неё сразу: человек выбрал папку, чтобы работать в ней,
  // а не просто чтобы она появилась в списке.
  await api('/api/workspaces', {action:'activate',
                                id: (r.workspaces || []).slice(-1)[0]?.id});
  await loadSession();
  refresh();
  toast('Работаем в: ' + clean);
}

// ---------- сессии ----------
async function newSession() {
  // Имя спрашиваем, но не требуем: пустое имя — не причина отменять
  // действие, о котором человек уже нажал кнопку.
  const name = await askText('Новая сессия', '', {
    placeholder: 'например: калькулятор (необязательно)',
    text: 'Та же папка, но чистая переписка: прошлый разговор останется в списке сессий.',
    okText: 'Создать',
  });
  if (name === null) return;
  const r = await api('/api/sessions', {action:'new', name: String(name).trim()});
  if (!r.ok) { toast(r.error || 'Не удалось создать сессию'); return; }
  clearChat();
  toast('Новая сессия в том же воркспейсе');
  await loadSession();
  refresh();
}
async function switchSession(id) {
  if (id === (S && S.session)) return;
  const r = await api('/api/sessions', {action:'switch', session_id: id});
  if (!r.ok) { toast(r.error || 'не вышло'); return; }
  clearChat();
  await loadSession();
  refresh();
}
async function renameSession(id) {
  const cur = ((S && S.sessions) || []).find(s => s.id === id);
  const name = await askText('Новое название сессии', cur ? cur.name : '',
                             {okText: 'Сохранить'});
  if (name === null || !String(name).trim()) return;
  const r = await api('/api/sessions', {action:'rename', session_id: id, name: String(name)});
  if (!r.ok) toast(r.error || 'не вышло');
  refresh();
}
async function dropSession(id, ev) {
  if (ev) ev.stopPropagation();
  const yes = await askYes('Удалить сессию?',
    'Переписка пропадёт. Задачи останутся в базе, но их история будет без контекста.');
  if (!yes) return;
  const r = await api('/api/sessions', {action:'remove', session_id: id});
  if (!r.ok) { toast(r.error || 'не вышло'); return; }
  if (id === (S && S.session)) { clearChat(); await loadSession(); }
  refresh();
}
function clearChat() {
  const log = $('msgs');
  if (log) log.innerHTML = '';
  curTask = null;
  const stop = $('stopBtn'); if (stop) stop.style.display = 'none';
}
// История активной сессии: без неё переключение выглядело бы пустым чатом.
async function loadSession() {
  const r = await api('/api/sessions', {action:'history'});
  if (!r.ok) return;
  clearChat();
  for (const e of (r.events || [])) handleEvent(e, true);
  const tasks = r.tasks || [];
  if (!tasks.length) {
    addMsg({who:'', text:'Новая сессия. Опишите задачу — агент начнёт с чистого листа.',
            kind:'sys'});
  }
}
function renderSpace() {
  const ws = (S && S.workspaces) || {workspaces:[], active:''};
  const sessions = (S && S.sessions) || [];
  const activeId = S && S.session;
  const cur = (ws.workspaces || []).find(w => w.id === ws.active);

  // Текущее место работы. Путь показан целиком: имя папки «zagent» ни о чём
  // не говорит, а человек обязан видеть, куда агент сейчас пишет.
  const marks = cur ? [
    cur.access === 1 ? 'только чтение'
      : (cur.access === 3 ? 'полный доступ' : 'чтение и запись'),
    'режим: ' + (cur.autonomy === 'yolo' ? 'делай сам'
      : cur.autonomy === 'strict' ? 'строго'
      : cur.autonomy === 'plan' ? 'сначала план' : 'обычный'),
    cur.max_steps + ' шагов',
    cur.exists ? '' : 'ПАПКИ НЕТ',
  ].filter(Boolean) : [];

  $('spaceNow').innerHTML = cur
    ? `<div class="t"><span class="ic">▸</span>Сейчас здесь</div>
       <div class="p" title="${esc(cur.path)}">${esc(cur.path)}</div>
       <div class="s">${esc(marks.join(' · '))}</div>
       <div class="s">сессия: <b>${esc(
          (sessions.find(s => s.id === activeId) || {}).name || '—')}</b>
          · задач в ней: ${(sessions.find(s => s.id === activeId) || {}).task_count || 0}</div>
       ${cur.is_code_root
         ? '<div class="warnbox">Это папка самого zagent. Всё, что агент здесь '
           + 'создаст, попадёт в код программы. Для обычной работы выбирают '
           + 'отдельную папку.</div>' : ''}`
    : '<div class="dim">Папка не выбрана</div>';

  $('sessionList').innerHTML = sessions.length
    ? sessions.map(s => `<div class="sess ${s.id===activeId?'on':''}"
            onclick="switchSession('${jsq(s.id)}')"
            oncontextmenu="renameSession('${esc(s.id)}');return false"
            title="ПКМ — переименовать">
        <span class="ic" style="color:${s.id===activeId?'var(--accent)':'var(--muted)'}">
          ${s.id===activeId?'●':'○'}</span>
        <span class="nm">${esc(s.name)}<div>${s.task_count||0} задач</div></span>
        <button class="x" onclick="dropSession('${jsq(s.id)}', event)"
                title="Удалить сессию">✕</button>
      </div>`).join('')
    : '<div class="empty">Сессий пока нет</div>';

  $('wsList2').innerHTML = (ws.workspaces || []).map(w => {
    const info = [
      w.access===1?'только чтение':w.access===3?'полный':'чтение+запись',
      w.autonomy, w.max_steps + ' шагов',
    ].join(' · ');
    return `<div class="fitem ${w.id===ws.active?'on':''}"
                 onclick="switchWs('${jsq(w.id)}')"
                 title="${esc(w.path)}">
      <span class="ic">${w.id===ws.active?'●':'○'}</span>
      <span class="nm">${esc(w.name)}
        <div class="dim mini">${esc(w.path)}</div>
        <div class="dim mini">${esc(info)}</div></span>
      ${w.exists ? '' : chip('нет')}
      ${w.id !== ws.active
        ? `<button class="x" onclick="dropWs('${jsq(w.id)}', event)"
                  title="Убрать из списка (файлы останутся)">✕</button>` : ''}
    </div>`;
  }).join('');

  // Папка для результатов всегда одна и всегда подходит, поэтому её проще
  // назвать прямо, чем искать в списке.
  const hint = $('wsHint');
  if (hint) {
    hint.innerHTML = ws.projects_dir
      ? `<div class="note">Папка для новых проектов: <code class="inl">${esc(ws.projects_dir)}</code>.
         Всё, что агент создаст, попадёт туда.</div>`
      : '';
  }
}

// Убрать папку из списка. Файлы не трогаем: папка может понадобиться снова,
// просто перестала быть текущей.
async function dropWs(id, ev) {
  if (ev) ev.stopPropagation();
  const w = ((S && S.workspaces) || {}).workspaces || [];
  const target = w.find(x => x.id === id);
  const yes = await askYes('Убрать папку из списка?',
    (target ? target.path + '\n\n' : '') +
    'Сами файлы останутся на месте — исчезнет только строка из списка.');
  if (!yes) return;
  const r = await api('/api/workspaces', {action:'remove', id});
  if (!r.ok) { toast(r.error || 'не получилось'); return; }
  toast('Папка убрана из списка');
  await loadSession();
  refresh();
}

function renderWs() {
  const ws = S.workspaces || {workspaces:[], active:''};
  // В селекторе у воркспейса путь, а не имя: две папки могут называться
  // одинаково, и различать их придётся по месту.
  $('wsSel').innerHTML = (ws.workspaces || []).map(w =>
    `<option value="${esc(w.id)}" ${w.id===ws.active?'selected':''}>${esc(w.name)} — ${esc(w.path)}</option>`
  ).join('');
  renderSpace();
}

// ---------- пинг и sanity ----------
// Долгие операции показываем кольцом: иначе нажатая кнопка 2-4 минуты
// выглядит как зависшая, и непонятно, работает ли вообще программа.
function busy(btnId, on, label) {
  const b = $(btnId);
  if (!b) return;
  if (on) {
    b.dataset.label = b.innerHTML;
    b.disabled = true;
    b.innerHTML = `<span class="ring"></span> ${esc(label || 'работа…')}`;
  } else {
    b.disabled = false;
    if (b.dataset.label) b.innerHTML = b.dataset.label;
  }
}
async function scan() {
  toast('Пересобираю каталог…');
  busy('scanBtn', true, 'каталог');
  await api('/api/scan',{});
  busy('scanBtn', false);
  refresh();
}
// Пинг без ref — все модели реестра. Раньше сюда слался ref всегда,
// и «Пинг» проверял одну модель вместо всех: 38 запросов превращались в 1,
// и список статусов почти не менялся.
async function pingAll() {
  busy('pingBtn', true, 'пингую');
  $('sendInfo').textContent = 'Пингую все модели, это займёт пару минут…';
  const r = await api('/api/ping', {});
  $('sendInfo').textContent = '';
  busy('pingBtn', false);
  if (!r.ok) { toast(r.error || 'пинг не начался'); return; }
  toast(`Проверено моделей: ${r.pinged}`);
  refresh();
}

// Пинг только тех, кто сейчас не отвечает. Дешевле полного и отвечает на
// вопрос «что снова ожило».
async function pingUnavailable() {
  const dead = (S.candidates || []).filter(r => {
    const s = (r.probe?.status || r.status || 'unknown');
    return !['ok', 'slow'].includes(s);
  });
  if (!dead.length) { toast('Все доступные модели отвечают'); return; }
  busy('pingBtn', true, 'недоступные');
  // Список недоступных уходит на сервер, а не используется только для подсчёта: `api('/api/ping', {})` без ref пингует **весь** реестр.
  // Кнопка обещала перепроверить недоступные, а проверяла все и рапортовала «из N недоступных».
  const r = await api('/api/ping', {refs: dead.map(x => x.ref)});
  $('sendInfo').textContent = '';
  busy('pingBtn', false);
  if (!r.ok) { toast(r.error || 'пинг не начался'); return; }
  toast(`Перепроверено: ${r.pinged} (из ${dead.length} недоступных)`);
  refresh();
}

// Кнопка пинга внутри строки модели: та же функция, но с ref.
async function pingOne(ref, node) {
  node?.classList.add('busy');
  const r = await api('/api/ping', {ref});
  node?.classList.remove('busy');
  if (!r.ok) { toast(r.error || 'не получилось'); return; }
  const probe = (r.results || {})[ref] || {};
  toast(`${probe.status || '?'}${probe.duration_ms ? ' · ' + (probe.duration_ms/1000).toFixed(1) + 'с' : ''}`);
  refresh();
}
async function sanityAll() {
  // Кольцо + полоса: sanity идёт в loop воркера и занимает минуты.
  $('sanityOut').innerHTML =
    `<div class="note"><span class="ring"></span> Проверяю адекватность, 2-4 минуты…</div>` +
    `<div class="barTrack" style="margin:0 10px 10px"><div class="barFill"></div></div>`;
  const r = await api('/api/sanity', {});
  renderSanity(r); refresh();
}
function renderSanity(r) {
  const rows = Object.values(r.reports || {}).sort((a,b) => (b.score||0)-(a.score||0));
  $('sanityOut').innerHTML = '<div class="note">Проверено ' + r.checked +
    ', пригодных ' + r.good + '</div>' +
    rows.map(x => `<div class="mgroup">
      <div class="row tight" style="padding:0 0 4px"><code class="inl">${esc(x.ref)}</code>${chip(x.verdict)}
        <span class="dim mini">${x.latency_ms} мс</span></div>
      <div class="mini dim" style="padding:0 0 4px">${x.checks.map(c =>
        (c.passed?'✔':'✘')+' '+esc(c.name)+': '+esc(c.detail)).join(' · ')}</div>
    </div>`).join('');
}
// \u0422\u0430\u0431\u043b\u0438\u0446\u0430 \u0441\u0442\u0430\u0442\u0443\u0441\u0430: \u0432\u0441\u0435 \u043c\u043e\u0434\u0435\u043b\u0438 \u0440\u0435\u0435\u0441\u0442\u0440\u0430, \u0430 \u043d\u0435 \u0442\u043e\u043b\u044c\u043a\u043e \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u0430\u044f.
// \u0420\u0430\u043d\u044c\u0448\u0435 \u0441\u043f\u0438\u0441\u043e\u043a \u0441\u043e\u0441\u0442\u043e\u044f\u043b \u0438\u0437 \u043e\u0434\u043d\u043e\u0439 \u0441\u0442\u0440\u043e\u043a\u0438 \u2014 \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u043e\u0439 \u043c\u043e\u0434\u0435\u043b\u0438, \u2014 \u0438
// \u00ab\u043f\u0438\u043d\u0433 \u0432\u0441\u0435\u0445\u00bb \u0431\u044b\u043b\u043e \u043d\u0435\u0432\u0438\u0434\u0438\u043c\u043e \u043d\u0438\u0433\u0434\u0435.
// Лазарет моделей: палаты вместо сухой таблицы статусов. Группы считает
// сервер (select.ward) — здесь только вывески и отсчёт, чтобы палата
// не разъезжалась с тем, что видно в списке моделей.
function renderWard() {
  const box = $('wardBox');
  if (!box) return;
  const groups = (S && S.ward) || [];
  const live = groups.filter(g => g.count);
  if (!groups.length) { box.innerHTML = ''; return; }
  if (!live.length) {
    box.innerHTML = '<div class="mini dim" style="padding:8px 12px">'
      + 'Лазарет пуст: ни одного на лечении, ни одного в реанимации.</div>';
    return;
  }
  const chipOf = {critical: 'bad', ward: 'warn', discharged: 'info', unseen: ''};
  let html = '<div class="row tight" style="padding:8px 12px 2px">';
  for (const g of live) {
    html += `<span class="chip ${chipOf[g.key] || ''}">${esc(g.title)} · ${g.count}</span>`;
  }
  html += '</div>';
  for (const g of live) {
    html += `<div class="mini dim" style="padding:4px 12px 0">`
          + `${esc(g.title)} — ${esc(g.note)}</div>`;
    const shown = g.items.slice(0, 6);
    for (const it of shown) {
      // Бэкофф — это и есть «курс лечения»: сколько ещё минут палата
      // держит модель. Нулевой отсчёт у живой палаты — ждём перепроверку.
      const left = it.cooldown_left > 0
        ? `бэкофф ${fmtLeft(it.cooldown_left)}`
        : (g.key === 'discharged' || g.key === 'unseen'
            ? '' : 'ждёт перепроверки');
      const err = it.error ? ` · ${esc(it.error.slice(0, 48))}` : '';
      html += `<div style="padding:2px 12px">`
            + `<span class="mini">${esc(it.model)}</span> `
            + `<span class="dim mini">${esc(it.gateway)}`
            + `${left ? ' · ' + left : ''}${err}</span></div>`;
    }
    if (g.count > shown.length) {
      html += `<div class="mini dim" style="padding:2px 12px">`
            + `… и ещё ${g.count - shown.length}</div>`;
    }
  }
  box.innerHTML = html;
}

// Голос статуса: конец задачи — вслух, если включено. Синтеза речи может
// не оказаться ни в системе, ни в текущем контексте браузера — тогда
// молчим, а не падаем: голос приятное добавление, а не условие работы.
function voiceSay(text) {
  try {
    if (localStorage.getItem('zagent.voice') !== 'on') return;
    const synth = window.speechSynthesis;
    if (!synth || !window.SpeechSynthesisUtterance) return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'ru-RU';
    synth.speak(u);
  } catch (err) { /* без голоса всё равно работает */ }
}

function voiceToggle() {
  const on = localStorage.getItem('zagent.voice') === 'on';
  localStorage.setItem('zagent.voice', on ? 'off' : 'on');
  renderVoiceBtn();
  if (!on) voiceSay('Голос включён');
}

function renderVoiceBtn() {
  const btn = $('voiceBtn');
  if (!btn) return;
  btn.textContent = localStorage.getItem('zagent.voice') === 'on'
    ? '🔊 голос: вкл' : '🔈 голос: выкл';
}

function renderPing() {
  // `S` появляется только после первого ответа состояния, а событие из
  // потока может прийти раньше. Без проверки это `TypeError` в обработчике
  // события, и весь список моделей оставался пустым до следующего обновления.
  const cands = (S && S.candidates) || [];
  const box = $('pingOut');
  if (!box) return;

  const autoBox = $('autoBox');
  if (autoBox) autoBox.innerHTML = renderAutoPing();
  renderKeyPower();

  if (!cands.length) { box.innerHTML = '<div class="empty">\u0420\u0435\u0435\u0441\u0442\u0440 \u043f\u0443\u0441\u0442</div>'; return; }

  const counts = {};
  for (const r of cands) {
    const s = (r.probe?.status || r.status || 'unknown');
    counts[s] = (counts[s] || 0) + 1;
  }
  const legend = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([s, n]) => `${chip(s)} ${n}`)
    .join(' &nbsp; ');

  const sel = selState();
  box.innerHTML = `<div class="mini dim" style="padding:6px 12px">${legend}
      &nbsp;\u00b7&nbsp; \u0441\u0435\u0439\u0447\u0430\u0441 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0435\u0442\u0441\u044f <b>${esc(sel.current || '\u2014')}</b></div>` +
    '<table id="pingTbl"><tr><th>\u041c\u043e\u0434\u0435\u043b\u044c</th><th>\u0428\u043b\u044e\u0437</th>' +
    '<th>\u0422\u0438\u0440</th><th>\u0421\u0442\u0430\u0442\u0443\u0441</th><th>\u0412\u0440\u0435\u043c\u044f</th>' +
    '<th>\u0422\u043e\u043a\u0435\u043d\u044b</th><th></th></tr>' +
    cands.map(r => {
      const p = r.probe || {};
      const state = p.status || r.status || 'unknown';
      const isCurrent = r.ref === sel.current;
      return `<tr${isCurrent ? ' class="on"' : ''}>
        <td><code class="inl">${esc(r.model)}${r.vision ? ' \ud83d\udc41' : ''}</code></td>
        <td class="mini">${esc(r.gateway)}</td><td class="dim">${r.tier}</td>
        <td>${chip(state)}</td>
        <td class="mini">${p.duration_ms ? (p.duration_ms/1000).toFixed(1)+'s' : '\u2014'}</td>
        <td class="mini">${p.tokens_in ? p.tokens_in+'+'+p.tokens_out : '\u2014'}</td>
        <td><button class="btn sm" onclick="pingOne('${jsq(r.ref)}', this)"
            title="\u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0442\u043e\u043b\u044c\u043a\u043e \u044d\u0442\u0443 \u043c\u043e\u0434\u0435\u043b\u044c">\u043f\u0438\u043d\u0433</button></td></tr>`;
    }).join('') + '</table>';
}

// \u0411\u043b\u043e\u043a \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u043e\u0439 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438: \u0441\u0447\u0451\u0442\u0447\u0438\u043a \u0434\u043e \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0433\u043e \u043f\u0438\u043d\u0433\u0430 \u0438
// \u0441\u043f\u0438\u0441\u043e\u043a \u043e\u0436\u0438\u0432\u0448\u0438\u0445. \u041e\u0436\u0438\u0432\u0448\u0438\u0435 \u2014 \u0433\u043b\u0430\u0432\u043d\u043e\u0435: \u0431\u0435\u0437 \u043d\u0438\u0445 \u0444\u043e\u043d\u043e\u0432\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430
// \u0432\u044b\u0433\u043b\u044f\u0434\u0438\u0442 \u043a\u0430\u043a \u043f\u0443\u0441\u0442\u0430\u044f \u0440\u0430\u0431\u043e\u0442\u0430.
// Сколько аккаунтов подключено и сколько выбито по лимиту.
//
// Число ключей — это и есть вычислительная мощность: лимиты у OpenRouter
// считаются на аккаунт, и десять моделей на одном исчерпанном ключе дают
// ровно ноль работающих моделей.
function renderKeyPower() {
  const box = $('keyBox');
  if (!box) return;
  const keys = (S && S.keys) || {};
  const sum = keys.summary || {};
  const rows = Object.keys(keys).filter(k => k !== 'summary' && keys[k]?.total);

  if (!rows.length) {
    box.innerHTML = '<div class="autoRow"><span class="dim mini">'
      + 'Ключи не заданы. Для работы агента нужен хотя бы один.</span></div>';
    return;
  }

  let html = `<div class="autoRow">
      <span class="sbadge ${sum.free_keys ? 'on' : 'warn'}"><i></i>
        аккаунтов свободно ${sum.free_keys} из ${sum.total_keys}</span>`;
  if (sum.total_keys > sum.free_keys) {
    // Причины разные, и сводить их к «выбито по лимиту» нельзя: пустой
    // аккаунт по лимиту не отпустит, его надо пополнять. Иначе человек
    // будет искать лимит там, где на самом деле нет денег.
    const broken = rows.flatMap(gid => (keys[gid].keys || [])
      .filter(k => k.blocked && k.reason !== '429')
      .map(k => k.reason));
    const detail = broken.length ? [...new Set(broken)].join(', ')
      : 'выбито по лимиту';
    html += '<span class="dim mini">' + esc(detail) + ': '
      + (sum.total_keys - sum.free_keys) + '</span>';
  }
  html += '</div>';

  html += '<div class="klist">' + rows.map(gid => {
    const g = keys[gid];
    const label = (S.gateways || []).find(x => x.id === gid)?.label || gid;
    // Кольцо заполняется при первом обращении, а список ключей из конфига
    // виден сразу. Пока счётчиков нет, рисуем точки по числу подключённых
    // ключей: иначе шлюз с девятью аккаунтами выглядит как пустой.
    const listed = (g.keys || []).length ? g.keys
      : Array.from({length: g.total || 0},
                   (_, i) => ({label: 'ключ ' + (i + 1), used: 0,
                               blocked: false, cooldown: 0}));
    // До 12 меток: длиннее список уже не читается, а детали видны по наведению.
    // Подпись собирается одной строкой целиком: разбивать шаблонную строку
    // на несколько строк здесь нельзя — закрывающая кавычка теряется среди
    // интерполяций и скрипт перестаёт парситься целиком.
    const marks = listed.slice(0, 12).map(k => {
      // Аккаунт, выбравший лимит в минуту, не выбит: он просто занят. Отличать
      // надо, иначе «NVIDIA выбита» будет написано про один исчерпанный аккаунт
      // из четырёх, и человек пойдёт искать проблему там, где её нет.
      const tight = k.rpm_limit && k.rpm_left !== undefined && k.rpm_left <= 3;
      const cls = k.blocked ? ' off' : (tight ? ' tight' : (k.used ? '' : ' idle'));
      const rpm = k.rpm_limit
        ? ` · в минуту ${k.rpm_left ?? k.rpm_limit} из ${k.rpm_limit}` : '';
      const tip = k.label + ' · запросов ' + k.used + rpm
        + (k.blocked ? ' · ждёт ' + fmtLeft(k.cooldown) : '');
      const glyph = k.blocked ? '×' : '·';
      return '<span class="kmark' + cls + '" title="' + esc(tip) + '">'
        + glyph + '</span>';
    }).join('');
    const more = listed.length > 12 ? ` +${listed.length - 12}` : '';
    // Сколько аккаунтов заведено — выводится числом, а не только метками.
    // Четыре ключа, показанные одной строкой точек, читаются как «один»:
    // метки одинаковые и расстояние между ними ничего не значит. Именно так
    // и вышло «у NVIDIA один ключ», когда их было четыре.
    const rpmTotal = (g.keys || []).filter(k => k.rpm_limit).length;
    const rpmNote = rpmTotal
      ? `<span class="krpm" title="${rpmTotal} аккаунтов, лимит ${esc(
          (g.keys || []).find(k => k.rpm_limit)?.rpm_limit || '?')} запросов в минуту на аккаунт">`
        + `${esc((g.keys || []).find(k => k.rpm_limit)?.rpm_limit || '?')}/мин</span>`
      : '';
    return `<div class="krow">
        <span class="kgw">${esc(label)}</span>
        <span class="kmarks">${marks}${more}</span>
        ${rpmNote}
        <span class="kfree" title="${g.available} свободно из ${g.total}">${g.available}/${g.total}</span>
      </div>`;
  }).join('') + '</div>';

  box.innerHTML = html;
}

function renderAutoPing() {
  const st = PING || {};
  // Отсчёт обязан что-то показывать и до первого пинга. Раньше
  // `next_in` появлялся только из события `ping_done`, то есть через
  // минуту после запуска, а до того горело «следующая проверка через —».
  // Идёт проверка — считать нечего, и ноль на месте отсчёта читался
  // как «сейчас будет». До первого пинга — «скоро»: показывать тут
  // прочерк значило не показывать ничего вообще.
  const left = st.running ? 'идёт' : (st.next_in != null ? fmtCountdown(st.next_in) : 'скоро');

  let html = `<div class="autoRow">
      <span class="sbadge${st.running ? ' warn' : ' on'}"><i></i>${
        st.running ? '\u0438\u0434\u0451\u0442 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430' : '\u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0441\u0430\u043c\u0430'}</span>
      <span class="dim mini pingNext">следующая через ${left}</span>`;
  if (st.since != null) {
    html += `<span class="dim mini">\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u044f\u044f ${fmtLeft(st.since)} \u043d\u0430\u0437\u0430\u0434</span>`;
  }
  html += '</div>';

  const last = (st.history || []).slice(-1)[0];
  if (last) {
    html += `<div class="mini dim" style="padding:2px 0 4px">
      \u0432 \u043f\u0440\u043e\u0448\u043b\u044b\u0439 \u0440\u0430\u0437 \u043e\u0442\u0432\u0435\u0447\u0430\u043b\u043e ${last.ok} \u0438\u0437 ${last.checked}</div>`;
  }

  const rec = Object.entries(st.recovered || {});
  if (rec.length) {
    const items = rec.slice(-6).map(([ref, n]) =>
      `<span class="chip ok" title="\u043e\u0436\u0438\u043b\u0430 ${n} \u0440\u0430\u0437">${
        esc(ref.split('/').slice(-1)[0])}</span>`).join(' ');
    html += `<div class="mini" style="padding:2px 0 4px">\u043e\u0436\u0438\u043b\u0438: ${items}</div>`;
  }
  return html;
}

function fmtLeft(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return s + ' с';
  const m = Math.round(s / 60);
  if (m < 60) return m + ' мин';
  return Math.round(m / 60) + ' ч';
}

// Отсчёт до события: минуты с секундами. Отдельная функция, потому что
// округление до целых минут делало живой таймер неотличимым от зависшего:
// «5 мин» не меняется две минуты подряд, и человек решал, что счётчик сломан.
function fmtCountdown(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return s + ' с';
  const m = Math.floor(s / 60);
  if (m < 60) return m + ':' + String(s % 60).padStart(2, '0');
  return Math.floor(m / 60) + ' ч ' + (m % 60) + ' мин';
}

// ---------- прочее ----------
async function setMode(m) {
  if (m === 'manual') {
    // В ручном режиме модель выбирается кликом по строке списка. Молча
    // подставлять первую — значит агент работает не на той модели, которую
    // пользователь считает выбранной.
    const current = selState().manual_ref;
    const r = await api('/api/mode', {mode:'manual',
      manual_ref: current || (S.candidates || [])[0]?.ref});
    if (!r.ok) { toast(r.error || 'не получилось'); refresh(); return; }
    refresh();
    foldOpenIfNoModel();
    return;
  }
  await api('/api/mode', {mode:'auto'}); refresh();
}

// Подсказка под переключателем режима: что сейчас выбрано и что делать дальше.
function renderModeNote() {
  const box = $('modeNote');
  const sw = $('modeSw');
  if (!box) return;
  const s = selState();
  const manual = s.mode === 'manual';
  if (sw) sw.classList.toggle('on', !manual);

  if (manual) {
    const ref = s.manual_ref;
    const model = (S.candidates || []).find(r => r.ref === ref);
    box.innerHTML = ref
      ? `Агент работает только с <b>${esc(model ? model.model : ref)}</b>.
         <span class="linkish" onclick="foldOpenIfNoModel()">Сменить</span>`
      : '<span class="warnText">Модель не выбрана — выберите её в списке ниже.</span>';
  } else {
    const total = s.total || (S.candidates || []).length;
    box.innerHTML = `Агент сам берёт лучшую доступную модель.
      <span class="dim">В реестре ${total}.</span>
      <span class="linkish" onclick="$('modeSel').value='manual';setMode('manual')">
        Выбрать вручную</span>`;
  }
}

// В ручном режиме список моделей — это и есть выбор, поэтому подсказку
// «сменить модель» раскрываем и подводим взглядом к списку.
function foldOpenIfNoModel() {
  $('modelList')?.scrollIntoView({behavior:'smooth', block:'nearest'});
}
async function cfg(fields) { await api('/api/config', fields); refresh(); }

// ---------- живые события ----------
function connect() {
  // lastEvent переживает перезагрузку вкладки. Без этого поток начинался с
  // since=0 и получал всю историю: до 200 чужих событий, каждое из которых
  // дёргало ещё и /api/state — до 400 параллельных запросов на пустом месте.
  const es = new EventSource('/api/events?since=' + lastEvent +
    (S && S.session ? '&session=' + encodeURIComponent(S.session) : ''));
  // Статус соединения бейджем: раньше была просто точка, и по ней нельзя было
  // понять, подключён ли поток или связь пропала.
  es.onopen  = () => {
    $('liveBadge').classList.add('on');
    $('liveTx').textContent = 'на связи';
  };
  es.onerror = () => {
    $('liveBadge').classList.remove('on');
    $('liveBadge').classList.add('warn');
    $('liveTx').textContent = 'нет связи';
  };
  es.onmessage = ev => {
    const e = JSON.parse(ev.data);
    // Модель ожила после лимита. Без этого события фоновая проверка молча
    // делала работу, и пользователь не знал, что у него снова есть выбор.
    if (e.type === 'recovered') {
      toast(`Модель снова отвечает: ${e.model || e.ref}`);
      addMsg({who:'sys', text:`Модель «${e.model || e.ref}» ожила (была ${e.was})`,
              kind:'sys'});
      refresh();
      return;
    }
    if (e.type === 'ping_done') {
      PING.last = e.at; PING.since = 0;
      PING.next_in = e.interval ?? PING.interval;
      PING.history = (PING.history || []).concat([e]).slice(-4);
      PING.running = false;
      if (e.recovered) toast(`Проверка: отвечало ${e.ok} из ${e.checked}`);
      renderPing();
      return;
    }
    if (e.type === 'ping_error') {
      PING.running = false;
      toast('Автопроверка: ' + (e.error || 'ошибка'));
      return;
    }
    if (e.id) rememberEvent(e.id);
    // Чужая сессия в переписке — помеха: в поток попадают события всех папок.
    if (e.session_id && S && e.session_id !== S.session) { refresh(); return; }
    // Событие, которое уже показано, повторно не рисуем: сервер отдаёт
    // событие и из backlog, и из очереди подписки.
    if (e.id && seen.has(e.id)) return;
    if (e.id) noteSeen(e.id);
    handleEvent(e, false);
    if (['finished','queued','started','verify','mode_chosen'].includes(e.type)) refresh();
  };
}
function handleEvent(e, replay) {
  // Событие части субагента: рисуем в его карточке и не выводим в общий
  // журнал. Иначе шаги всех частей шли бы вперемешку с шагами главного
  // агента, и понять, кто что делал, было бы невозможно.
  if (e.sub && onSubEvent(e)) return;
  if (e.type === 'swarm_skipped') {
    addMsg({who:'⚙', kind:'sys',
            text:`Субагенты не понадобились: ${e.reason}. Задачу выполняет один агент.`});
    return;
  }
  if (e.type === 'swarm_failed') {
    addMsg({who:'⚙', kind:'sys',
            text:`Не удалось разбить задачу (${e.stage}): ${e.error}. Выполняю её целиком.`});
    return;
  }
  if (e.type === 'swarm_done') {
    addMsg({who:'⚙', kind:'sys',
            text:`Части отработали: ${e.ok} из ${e.parts} за ` +
                 `${Math.round((e.elapsed_ms || 0) / 1000)} с. Собираю результат.`});
    return;
  }
  // План роя виден сразу: сколько рабочих, сколько в резерве и почему.
  // Резерв без объяснения выглядит как «недоделанная работа».
  if (e.type === 'swarm_plan') {
    const p = e.plan || {};
    const w = (p.workers || []).length;
    const r = (p.reserve || []).length;
    addMsg({who:'⚙', kind:'sys',
            text:`Рой: ${w} рабочих, ${r} в резерве. ${p.note || ''}` +
                 ((p.unassigned && p.unassigned.length)
                   ? ` Не досталось аккаунта: ${p.unassigned.join(', ')}.`
                   : '')});
    renderHerdPlan(p);
    return;
  }
  // Подмена видна отдельно от результата: человек должен понимать, что часть
  // не бросили, а перевели на другой аккаунт и продолжили с чекпоинта.
  if (e.type === 'swarm_handoff') {
    addMsg({who:'⚙', kind:'sys',
            text:`«${e.sub}»: ${e.from} закончился — перевожу на ${e.to}. Причина: ${e.reason}`});
    return;
  }
  if (e.type === 'swarm_resumed') {
    addMsg({who:'⚙', kind:'sys', text:`«${e.sub}»: ${e.note}.`});
    return;
  }
  if (e.type === 'swarm_part_failed') {
    addMsg({who:'⚙', kind:'sys', text:`«${e.sub}» не выполнена: ${e.error}`});
    return;
  }
  if (e.type === 'swarm_partial') {
    const wait = (e.pending || []).join(', ');
    addMsg({who:'⚙', kind:'sys',
            text:`Главный агент собрал промежуточный результат: готово ${(e.done || []).length}, в работе: ${wait || '—'}.` +
                 (e.note ? ` ${e.note}` : '')});
    return;
  }
  // Проверяющие отработали раньше сборки. Их вердикты и есть то, ради чего
  // сборщику не приходится перечитывать всё заново, поэтому видно их должно
  // быть здесь, а не только в итоговой сводке.
  if (e.type === 'swarm_verified') {
    const bad = (e.problems || []).length;
    const skipped = (e.unknown || []).length;
    let text = `Проверили ${e.checked} частей, проверяющих ${e.checkers}, ` +
               `${Math.round((e.elapsed_ms || 0) / 1000)} с.`;
    if (bad) text += ` Проблемы: ${e.problems.join(', ')}.`;
    if (skipped) text += ` Не удалось проверить: ${e.unknown.join(', ')}.`;
    if (!bad && !skipped) text += ' Все части в порядке.';
    addMsg({who:'⚙', kind:'sys', text:text});
    return;
  }
  // Решение «Авто» по режиму. Показывается в переписке и остаётся под
  // кнопкой режима: человек должен видеть не только что выбрано, но и
  // почему, иначе «Авто» выглядит как произвол.
  if (e.type === 'started') {
    PROG.active = true;
    PROG.maxSteps = Number(e.max_steps || 0);
    PROG.steps = 0;
    PROG.tool = 'думает';
    PROG.file = '';
    PROG.note = '';
    renderProgress();
    return;
  }
  if (e.type === 'mode_chosen') {
    AUTO_PICK = e;
    renderAutoNote();
    if (!replay) {
      addMsg({who:'⚙', kind:'sys',
              text: `Режим: ${e.mode || 'обычный'}` +
                    (e.reason ? ` — ${e.reason}` : '') +
                    (e.source === 'heuristic' ? '\n(решено по признакам в тексте задачи)'
                                               : '')});
    }
    return;
  }
  if (e.type === 'step') {
    const s = e.step;
    // Счётчики хода: без них полоса показывала бы время и ничего больше.
    if (PROG.active) {
      PROG.steps = Number(s.index || 0);
      if (e.tokens != null) PROG.tokens = Number(e.tokens) || 0;
      if (e.budget_limit) PROG.budget = Number(e.budget_limit) || 0;
      // Пустой `note` — иначе требование «продолжи» из прошлой попытки
      // осталось бы висеть на полосе вместо текущего занятия.
      if (s.phase === 'thinking') { PROG.tool = 'думает'; PROG.file = ''; }
      PROG.note = '';
      renderProgress();
    }
    if (s.phase === 'thinking') {
      addMsg({who:'агент', text:s.text, model:s.model, ms:s.duration_ms,
              kind: s.ok ? 'assistant' : 'sys'});
    } else {
      $('msgs').insertAdjacentHTML('beforeend',
        `<div class="toolline ${s.ok?'':'bad'}"><span class="nm">${esc(s.tool||s.phase)}${
          (s.file || s.path || s.tool_target || '') ? ' · ' + esc(s.file || s.path || s.tool_target) : ''
        }</span>
         <span class="tx">${esc(s.text)}</span></div>`);
      $('msgs').scrollTop = $('msgs').scrollHeight;
    }
  } else if (e.type === 'tool') {
    // Главный ответ на вопрос «чем занят агент»: имя инструмента и файл.
    if (PROG.active) {
      PROG.tool = e.tool || 'инструмент';
      PROG.file = e.file || e.path || '';
      PROG.note = '';
      renderProgress();
    }
  } else if (e.type === 'verify') {
    const v = e.verification;
    $('msgs').insertAdjacentHTML('beforeend',
      `<div class="verify ${v.ok?'':'bad'}">${v.ok?'✔':'✘'} проверил ${esc(v.path)}: ${esc(v.detail)}</div>`);
    $('msgs').scrollTop = $('msgs').scrollHeight;
  } else if (e.type === 'permission_requested') {
    addMsg({who:'🔐', text:'Агент просит доступ вне воркспейса:\n' + (e.path || ''), kind:'sys'});
    // При восстановлении истории окно и не нужно: запрос виден в переписке,
    // а окончательное решение всё равно принимается по кнопке.
    if (!replay) checkPermissions();
  } else if (e.type === 'permission_decided') {
    addMsg({who: e.allow ? '✅' : '⛔',
            text: e.allow
              ? `Доступ разрешён: ${e.path}` + (e.scope === 'always' ? ' (навсегда)' : '')
              : `Доступ запрещён: ${e.path}`,
            kind:'sys'});
  } else if (e.type === 'question') {
    addMsg({who:'агент', text:'Вопрос: ' + e.question, kind:'sys'});
  } else if (e.type === 'budget') {
    addMsg({who:'бюджет', text:e.warning, kind:'sys'});
  } else if (e.type === 'keys_needed') {
    // Работа идёт, но вчетверо медленнее. Без этой строки человек видит
    // «агент тупит», хотя на деле запросы просто стоят в очереди.
    const where = (e.empty_gateways || []).join(', ');
    addMsg({who: '🔑 ключи',
            text: e.reason
                + (where ? '\nСвободных нет у шлюзов: ' + where + '.' : '')
                + '\nДобавь ключ в config/secrets.local.json — задача '
                + 'продолжится, просто сразу станет быстрее.',
            kind: 'sys'});
  } else if (e.type === 'continuation') {
    // Задача не сбой, а продолжение: лимит шагов закончился, а работа — нет.
    // Без этой строки интерфейс молчал бы, и человек решил бы, что агент
    // завис или сломался.
    addMsg({who: `продолжение ${e.attempt} из ${e.of}`,
            text: `Шаги закончились (${e.reason || 'лимит исчерпан'}). `
                + `Даю ещё ${e.extra_steps} шагов и продолжаю с того же места.`
                + (e.summary ? '\n\nЧто уже было:\n' + e.summary : ''),
            kind: 'sys'});
  } else if (e.type === 'continuation_started') {
    addMsg({who: 'продолжаю',
            text: `Попытка ${e.attempt}, лимит шагов теперь ${e.max_steps}.`,
            kind: 'sys'});
    // Полоска остаётся на экране: задача не закончилась, а новый лимит
    // надо видеть сразу — иначе полоса молча стоит на нуле.
    PROG.active = true;
    PROG.maxSteps = Number(e.max_steps || PROG.maxSteps);
    PROG.steps = 0;
    PROG.tool = 'продолжаю';
    PROG.file = '';
    PROG.note = '';
    renderProgress();
  } else if (e.type === 'continuation_exhausted') {
    addMsg({who: 'стоп',
            text: `Шаги закончились ${e.continuations} раз подряд `
                + `(${e.reason || 'лимит исчерпан'}). Что успел — выше в отчёте.`,
            kind: 'sys'});
    progressOff();
  } else if (e.type === 'finished') {
    if (e.status === 'done') {
      addMsg({who:'готово', text:'Задача выполнена.', kind:'sys'});
      renderArtifacts(e.artifacts || []);
      voiceSay('Задача выполнена');
    }
    else if (e.status === 'failed') {
      addMsg({who:'сбой', text:e.result?.last || 'не удалось', kind:'sys'});
      voiceSay('Задача не удалась');
    }
    else if (e.status === 'cancelled') addMsg({who:'отмена', text:'Задача отменена.', kind:'sys'});
    if (!replay) { curTask = null; $('stopBtn').style.display = 'none'; }
    progressOff();
  } else if (e.type === 'geo_start') {
    GEO.running = true;
    GEO.progress = {done:0, total:0, current:'', phase:'старт'};
    GEO.log = [];
    renderModels();
  } else if (e.type === 'geo_progress') {
    // Живая телеметрия: видно, какая модель проверяется и сколько осталось.
    if (e.kind === 'model') {
      GEO.progress.done = e.done || GEO.progress.done;
      GEO.log.push(ruMarkOf(e.status) + ' ' + (e.model || e.ref || ''));
    } else if (e.kind === 'checking') {
      GEO.progress.current = e.model || '';
    } else if (e.kind === 'pause') {
      GEO.progress.phase = 'пауза между шлюзами';
    } else if (e.kind === 'retry') {
      GEO.progress.phase = 'повтор после 429';
    }
    if (e.total) GEO.progress.total = e.total;
    if (e.model) GEO.progress.current = e.model;
    renderModels();
  } else if (e.type === 'geo_done') {
    GEO.running = false;
    GEO.progress.phase = 'готово';
    renderModels();
  } else if (e.type === 'geo_finished') {
    GEO.running = false;
    if (e.mode === 'direct') GEO.directDone = true;
    if (e.ok === false) toast('Замер не удался: ' + (e.error || 'неизвестно'));
    else if (e.mode === 'direct') toast('Замер без VPN готов. Теперь включите VPN и нажмите «Замер с VPN»');
    else toast('Замер с VPN готов');
    refresh();
  } else if (e.type === 'stranded') {
    addMsg({who:'сбой',
            text:`${e.count} задач потеряли запрос на доступ и закрыты как невыполненные`,
            kind:'sys'});
  }
}
function ruMarkOf(status) {
  const map = {ok:'✔', slow:'✔', empty:'✔', limited:'⚠', blocked:'✘', down:'✘'};
  return map[status] || '·';
}

// ---------- обновление ----------
async function refresh() {
  const state = await api('/api/state');
  // Ответ с ошибкой нельзя класть в `S`: дальше идут обращения к `S.region`
  // и `S.status_counts`, и вместо «сервер не отвечает» человек увидел бы
  // «Cannot read properties of undefined».
  if (!state || state.error || state.ok === false) {
    $('sendInfo').textContent = '';
    toast('Состояние недоступно: ' + ((state && state.error) || 'пустой ответ'));
    return;
  }
  S = state;
  // Имя `st` здесь перекрывало функцию selState() — состояние селектора. Из-за
  // этого refresh падал на последней строке, и весь интерфейс замирал после
  // первого обновления: ни модели, ни очередь, ни файлы.
  const c = S.status_counts || {};
  $('topinfo').innerHTML =
    `<b>${(S.gateways||[]).length}</b> шлюзов · <b>${(S.candidates||[]).length}</b> моделей · ` +
    `ok <b>${c.ok||0}</b> · лимит <b>${c.limited||0}</b> · заблокировано <b>${c.blocked||0}</b>` +
    (S.last_error ? ` · <span class="chip bad">${esc(S.last_error.slice(0,40))}</span>` : '');

  renderWs();
  renderModels();
  renderTasks();
  checkPermissions();
  renderPing();
  renderWard();
  renderVoiceBtn();
  // Число субагентов зависит от свободных аккаунтов, а они меняются сами:
  // модель могла выбиться по лимиту. Пересчитываем на каждом обновлении,
  // иначе режим предлагал бы шесть субагентов при двух живых аккаунтах.
  tuneModes();
  renderModeBtn();
  renderAutoNote();

  // Сессия видна всегда: по ней понятно, какая переписка на экране.
  const sess = (S.sessions || []).find(s => s.id === S.session);
  $('newSessBtn').title = sess
    ? `Сессия: ${sess.name} · ${sess.task_count || 0} задач. Начать новую в этом же воркспейсе`
    : 'Новая сессия в этом же воркспейсе';

  const cfgd = S.config || {};
  $('accSel').value = cfgd.access; $('autoSel').value = cfgd.autonomy;
  $('escSel').value = cfgd.escalation; $('stepsIn').value = cfgd.max_steps;
  $('boundSel').value = S.soft_boundary ? 'soft' : 'hard';
  $('vpnSel').value = cfgd.avoid_vpn ? 'avoid' : 'off';
  renderVpnNote();
  // Состояние автопинга приходит каждым ответом состояния. Раньше эти данные
  // жили только в событии `ping_done`, и до первого завершённого пинга
  // «следующая проверка через —» висело прочерком минуту после запуска.
  // Тик уменьшает счётчик на месте, поэтому здесь берём его заново.
  if (S.ping) {
    PING.running = !!S.ping.running;
    PING.interval = S.ping.interval ?? PING.interval;
    PING.last = S.ping.last ?? PING.last;
    PING.since = S.ping.since ?? null;
    PING.history = (S.ping.history || PING.history) || [];
    PING.recovered = S.ping.recovered || PING.recovered;
    // Значение из состояния — истина, даже когда оно пустое. Раньше здесь
    // стояло «оставь прежнее», и после разового пинга локальный счётчик
    // навсегда застревал на нуле: сервер отдаёт `next_in: null`, пока
    // следующий пинг ещё не запланирован, а интерфейс держал «0 с».
    PING.next_in = S.ping.next_in != null ? S.ping.next_in : null;
  }
  renderPing();
  // Замер мог завершиться, пока вкладка была неактивна: восстанавливаем
  // состояние из ответа сервера, иначе кнопки остались бы заблокированы.
  if (S.region) {
    GEO.running = !!S.region.running;
    if (S.region.progress) GEO.progress = S.region.progress;
    if (S.region.log) GEO.log = S.region.log;
    // Прямым считается замер без VPN, а не любой: `measured` рос от
    // замера с VPN, и интерфейс показывал «замер без VPN сделан»,
    // разблокируя второй шаг при первом непроведённом.
    const direct = (S.region.summary.samples || [])
      .some(x => x && x.mode === 'direct');
    if (direct) GEO.directDone = true;
  }
  const s = selState();
  if (s.mode) $('modeSel').value = s.mode;
  $('pauseBtn').textContent = S.paused ? 'продолжить' : 'пауза';

  renderModeNote();
  renderModelBadge();
  renderGeoInto();
  $('geoHint').textContent = geoHintText();
  // Счётчик автопинга живёт своей жизнью между ответами состояния: он
  // должен идти вниз каждую секунду, а не обновляться раз в 15 секунд.
  tickPingCountdown();
  api('/api/ping/status', {}).then(r => {
    if (r && r.ok) {
      // Только поля отсчёта: `PING = r` целиком затирало бы локальный
      // счётчик, который уменьшается тиком каждую секунду.
      PING.running = !!r.running;
      PING.interval = r.interval ?? PING.interval;
      PING.since = r.since ?? null;
      PING.next_in = r.next_in != null ? r.next_in : null;
      PING.history = r.history || PING.history;
      PING.recovered = r.recovered || PING.recovered;
      renderPing();
    }
  }).catch(() => {});

  if (!GUIDE) loadGuide('opencode');
  // Первая отрисовка приходит без GUIDE: ключи шлюзов пустеют до его загрузки.
  if (GUIDE && !$('modelList').children.length) renderModels();
}

// Панель доступности из РФ живёт в свёрнутом блоке, но пока идёт замер —
// блок поднимают, иначе прогресс несколько минут не видно.
function renderGeoInto() {
  const box = $('fGeo');
  if (box) box.innerHTML = geoPanel();
}

// Открыть блок доступности из РФ по кнопке. Отдельная функция, потому что
// вызов fold('fGeo') полагался на предыдущий элемент и молча ничего не делал,
// если верстка сдвинулась.
function openFold(id) {
  const body = $(id);
  if (!body) return;
  const head = body.previousElementSibling;
  if (!head) return;
  if (body.hasAttribute('hidden')) fold(head);
  body.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

// Обратный отсчёт до следующего автопинга. Считает на месте, потому что
// ответ сервера приходит раз в 15 секунд, а «через 4 мин» должно уменьшаться
// на глазах.
function tickPingCountdown() {
  if (!PING || PING.next_in == null) return;
  // Счётчик уменьшается всегда, даже если панель моделей сейчас свёрнута.
  // Раньше тик делал `return` до этого, и цифра замирала на том, что
  // показал последний refresh, — отсчёт выглядел сломанным.
  PING.next_in = Math.max(0, PING.next_in - 1);
  const box = $('autoBox');
  if (!box || !box.isConnected) return;
  const label = box.querySelector('.pingNext');
  if (label) label.textContent = 'следующая через ' + fmtCountdown(PING.next_in);
}
setInterval(() => {
  if (PING && PING.since != null) PING.since += 1;
  tickPingCountdown();
}, 1000);

// Короткая подпись на заголовке свёрнутого блока: сколько моделей проверено.
function geoHintText() {
  const rs = (S && S.regions) || {counts:{}, measured:0};
  const c = rs.counts || {};
  if (rs.measured) return `\u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d\u043e ${rs.measured}: \u2714${c.ok||0} \u2713${c.vpn||0} \u2717${c.blocked||0}`;
  return '\u043d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d\u043e';
}

// ---------- старт ----------
initTheme();
loadTree('.');
refresh().then(() => loadSession());
connect();
// Таблица статуса и счётчик автопинга обновляются, когда видна вкладка
// «Статус»: остальное время опрос сервера незачем.
setInterval(() => {
  const tab = document.getElementById('p-status');
  if (S && tab && tab.classList.contains('on')) refresh();
}, 15000);
</script>
</body>
</html>
"""
