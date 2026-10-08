/* Neural Archive — смена картинок в герое.
 *
 * Что здесь и зачем
 * ------------------
 * На первом экране стоит карусель: несколько картинок сменяются сами,
 * с прозрачным переходом, без «щелчков». Раньше там была одна
 * статичная заливка, и страница выглядела пусто на любом экране
 * шире, чем смотреть в текст.
 *
 * Почему без библиотеки
 * ---------------------
 * Карусель на 40 строк не стоит чужой зависимости: её всё равно
 * пришлось бы переписывать под вес и тему. Здесь всё на глазах.
 *
 * Осторожно: картинка не должна мешать читать
 * --------------------------------------------
 * Под каждым кадром лежит затемняющая подложка. Без неё светлый
 * кадр делает белый заголовок нечитаемым, а это ровно тот случай,
 * когда вёрстка ломается молча и заметить можно только глазами.
 */

'use strict';

/** Слайдер в герое. Запускается сам, когда разметка готова. */
class HeroSlider {
  /**
   * @param {HTMLElement} root — контейнер со слайдером
   */
  constructor(root) {
    this.root = root;
    this.slides = [...root.querySelectorAll('.slide')];
    this.dots = [...root.querySelectorAll('.slide-dot')];
    this.current = -1;
    this.timer = 0;
    // Пауза, когда вкладка не видна и когда на слайдер навели мышью:
    // иначе смена продолжается в фоне и человек вер��ается к смене
    // кадра, не успев прочитать предыдущий.
    this.visible = !document.hidden;
    this.hovered = false;
    // Столько показываем каждый кадр. Меньше — не успевают прочитать,
    // больше — начинают скучать.
    this.delay = 7000;
  }

  /** Показать кадр с индексом index. */
  show(index) {
    if (!this.slides.length) return;
    const total = this.slides.length;
    const next = ((index % total) + total) % total;
    if (next === this.current) return;

    for (const [i, slide] of this.slides.entries()) {
      // Класс `on` вешается только на текущий кадр, а предыдущий
      // гасится через `off`. Так переход виден: если повесить сразу
      // `on` следующему, старый кадр исчезнет мгновенно.
      slide.classList.toggle('on', i === next);
      slide.classList.toggle('off', i !== next);
    }
    for (const [i, dot] of this.dots.entries()) {
      dot.classList.toggle('on', i === next);
      // Для доступности: текущий кадр помечается и визуально, и
      // словами — иначе скринридер не скажет, где мы находимся.
      dot.setAttribute('aria-current', i === next ? 'true' : 'false');
    }
    this.current = next;
  }

  /** Запустить автосмену. */
  play() {
    this.stop();
    if (!this.visible || this.hovered) return;
    this.timer = window.setInterval(() => {
      this.show(this.current + 1);
    }, this.delay);
  }

  /** Остановить автосмену. */
  stop() {
    if (this.timer) {
      window.clearInterval(this.timer);
      this.timer = 0;
    }
  }

  /** Переключить источник кадра: по наведению, по фокусу, по видимости. */
  sync() {
    if (this.visible && !this.hovered) this.play();
    else this.stop();
  }

  start() {
    this.show(0);
    this.sync();

    for (const [i, dot] of this.dots.entries()) {
      dot.addEventListener('click', () => {
        this.show(i);
        // Перезапуск таймера: иначе смена произойдёт через остаток
        // прошедшего интервала, а не через полный срок, и кадр
        // пролистается раньше, чем его успели прочитать.
        this.sync();
      });
    }

    this.root.addEventListener('mouseenter', () => {
      this.hovered = true;
      this.sync();
    });
    this.root.addEventListener('mouseleave', () => {
      this.hovered = false;
      this.sync();
    });

    document.addEventListener('visibilitychange', () => {
      this.visible = !document.hidden;
      this.sync();
    });

    // Стрелки влево-вправо переключают кадр: так привычны все, кто
    // пользовался галереями, и это работает без мыши.
    this.root.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowRight') {
        event.preventDefault();
        this.show(this.current + 1);
        this.sync();
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        this.show(this.current - 1);
        this.sync();
      }
    });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const root = document.querySelector('.hero-slider');
  if (!root) return;

  // Картинка рисуется на сервере и может ещё не доехать. Пока её
  // нет, показываем заливку: пустой кадр с текстом поверх выглядит
  // как готовый, а сломанная картинка — как ошибка.
  let broken = 0;
  for (const image of root.querySelectorAll('img')) {
    image.addEventListener('error', () => {
      image.classList.add('missing');
      broken += 1;
      // Когда не показалась ни одна картинка, подпись «слайдер» только
      // мешает: убираем её целиком.
      if (broken >= root.querySelectorAll('img').length) {
        root.classList.add('no-images');
      }
    });
  }

  new HeroSlider(root).start();
});