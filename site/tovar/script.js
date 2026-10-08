// Поведение страницы NovaTech Store.
//
// Что изменилось по сравнению с шаблоном
// -------------------------------------
// Скрипт изначально был написан для другой страницы: в нём есть
// обработка аккордеона (`.faq-item`) и модального окна (`#modal`),
// а в разметке магазина ни того, ни другого нет. Обработчик модалки
// вызывал `addEventListener` на `null` и ронял весь блок — в консоли
// `TypeError: Cannot read properties of null`, а вместе с ним не
// работали появление секций и плавная прокрутка: они находились
// ниже по файлу.
//
// Теперь каждый обработчик сначала проверяет, есть ли его элемент.
// Поведение не изменилось — просто перестало ломать страницу там,
// где нужного блока нет.

document.addEventListener('DOMContentLoaded', () => {

  // 1. Липкая шапка: при прокрутке появляется фон и граница.
  const header = document.getElementById('header');
  if (header) {
    const onScroll = () => {
      header.classList.toggle('scrolled', window.scrollY > 50);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();                     // сразу: страница могла загрузиться
  }                               // уже прокрученной — восстановлением кнопки

  // 2. Появление секций при прокрутке.
  //
  // Если браузер не знает IntersectionObserver, элементы показываются
  // сразу: иначе страница осталась бы пустой — элементы навсегда
  // остались бы с opacity: 0 из-за того, что класс не навесился.
  const fade = document.querySelectorAll('.fade-in');
  if (fade.length) {
    if ('IntersectionObserver' in window) {
      const appear = new IntersectionObserver((entries, observer) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add('visible');
          observer.unobserve(entry.target);
        });
      }, { threshold: 0.15, rootMargin: '0px 0px -50px 0px' });

      fade.forEach((element) => {
        // Элемент ниже первого экрана показывается сразу, иначе он
        // мог остаться пустым, если наблюдатель не сработал.
        const box = element.getBoundingClientRect();
        if (box.top < window.innerHeight) {
          element.classList.add('visible');
        } else {
          appear.observe(element);
        }
      });
    } else {
      fade.forEach((element) => element.classList.add('visible'));
    }
  }

  // 3. Плавная прокрутка по якорям.
  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener('click', (event) => {
      const id = anchor.getAttribute('href');
      if (!id || id === '#') return;         // «#» — заглушка, не якорь
      const target = document.querySelector(id);
      if (!target) return;                   // якоря нет: молча уходим
      event.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  // 4. Аккордеон FAQ. В магазине его нет, но если блок появится —
  //    заработает, а не упадёт.
  const faqItems = document.querySelectorAll('.faq-item');
  faqItems.forEach((item) => {
    const question = item.querySelector('.faq-question');
    if (!question) return;                  // нет заголовка — не на что вешать
    question.addEventListener('click', () => {
      faqItems.forEach((other) => {
        if (other !== item) other.classList.remove('active');
      });
      item.classList.toggle('active');
    });
  });

  // 5. М��дальное окно. В разметке его нет; обработчики навешиваются
  //    только если все части на месте.
  const modal = document.getElementById('modal');
  const closeButton = document.getElementById('modal-close');
  const modalForm = document.getElementById('modal-form');
  const openButtons = document.querySelectorAll('.open-modal');

  if (modal && openButtons.length) {
    const open = () => {
      modal.classList.add('active');
      document.body.style.overflow = 'hidden';
    };
    const close = () => {
      modal.classList.remove('active');
      document.body.style.overflow = '';
    };

    openButtons.forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        open();
      });
    });
    if (closeButton) closeButton.addEventListener('click', close);
    modal.addEventListener('click', (event) => {
      if (event.target === modal) close();
    });
    if (modalForm) {
      modalForm.addEventListener('submit', (event) => {
        event.preventDefault();
        close();
        modalForm.reset();
      });
    }
  }
});
