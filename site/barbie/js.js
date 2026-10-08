/* ============================================================
   PINK ÉLITE — LUXURY NAIL STUDIO
   JavaScript: интерактив, анимации, валидация
   ============================================================ */

'use strict';

/* ============================================================
   1. PRELOADER
   ============================================================ */
(function initPreloader() {
  const preloader = document.getElementById('preloader');
  if (!preloader) return;

  const hidePreloader = () => {
    preloader.classList.add('hidden');
    document.body.style.overflow = '';
    setTimeout(() => {
      preloader.style.display = 'none';
    }, 700);
  };

  document.body.style.overflow = 'hidden';

  window.addEventListener('load', () => {
    setTimeout(hidePreloader, 1400);
  });

  // Фолбэк: если load не сработает за 4 секунды
  setTimeout(hidePreloader, 4000);
})();

/* ============================================================
   2. CUSTOM CURSOR
   ============================================================ */
(function initCustomCursor() {
  if (window.matchMedia('(max-width: 1024px)').matches) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const cursor = document.getElementById('cursor');
  const cursorFollow = document.getElementById('cursorFollow');
  if (!cursor || !cursorFollow) return;

  let mouseX = 0;
  let mouseY = 0;
  let followX = 0;
  let followY = 0;

  document.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
    cursor.style.transform = `translate(${mouseX}px, ${mouseY}px) translate(-50%, -50%)`;
  });

  // Плавное следование
  const animateFollow = () => {
    followX += (mouseX - followX) * 0.15;
    followY += (mouseY - followY) * 0.15;
    cursorFollow.style.transform = `translate(${followX}px, ${followY}px) translate(-50%, -50%)`;
    requestAnimationFrame(animateFollow);
  };
  animateFollow();

  // Hover-эффект на интерактивных элементах
  const interactiveSelectors = 'a, button, input, textarea, select, .service, .master, .project, .gallery__item, .review, .filter, .gallery__filter, .pricing__tab, .faq__question';

  document.querySelectorAll(interactiveSelectors).forEach((el) => {
    el.addEventListener('mouseenter', () => {
      cursorFollow.classList.add('hover');
    });
    el.addEventListener('mouseleave', () => {
      cursorFollow.classList.remove('hover');
    });
  });

  // Скрываем курсор при уходе со страницы
  document.addEventListener('mouseleave', () => {
    cursor.style.opacity = '0';
    cursorFollow.style.opacity = '0';
  });

  document.addEventListener('mouseenter', () => {
    cursor.style.opacity = '1';
    cursorFollow.style.opacity = '1';
  });
})();

/* ============================================================
   3. HEADER SCROLL
   ============================================================ */
(function initHeaderScroll() {
  const header = document.getElementById('header');
  const toTop = document.getElementById('toTop');
  if (!header) return;

  let lastScroll = 0;
  let ticking = false;

  const updateHeader = () => {
    const scrollY = window.scrollY;

    if (scrollY > 40) {
      header.classList.add('scrolled');
    } else {
      header.classList.remove('scrolled');
    }

    if (toTop) {
      if (scrollY > 600) {
        toTop.classList.add('show');
      } else {
        toTop.classList.remove('show');
      }
    }

    lastScroll = scrollY;
    ticking = false;
  };

  window.addEventListener('scroll', () => {
    if (!ticking) {
      requestAnimationFrame(updateHeader);
      ticking = true;
    }
  }, { passive: true });

  updateHeader();

  // Кнопка "Наверх"
  if (toTop) {
    toTop.addEventListener('click', () => {
      window.scrollTo({
        top: 0,
        behavior: 'smooth'
      });
    });
  }
})();

/* ============================================================
   4. BURGER MENU
   ============================================================ */
(function initBurgerMenu() {
  const burger = document.getElementById('burger');
  const nav = document.getElementById('nav');
  if (!burger || !nav) return;

  const openMenu = () => {
    burger.classList.add('active');
    nav.classList.add('open');
    document.body.style.overflow = 'hidden';
  };

  const closeMenu = () => {
    burger.classList.remove('active');
    nav.classList.remove('open');
    document.body.style.overflow = '';
  };

  burger.addEventListener('click', () => {
    if (nav.classList.contains('open')) {
      closeMenu();
    } else {
      openMenu();
    }
  });

  // Закрываем меню при клике по ссылке
  nav.querySelectorAll('.nav__link').forEach((link) => {
    link.addEventListener('click', closeMenu);
  });

  // Закрываем при клике по пустому месту (для мобильной версии)
  nav.addEventListener('click', (e) => {
    if (e.target === nav) closeMenu();
  });

  // Закрываем по Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && nav.classList.contains('open')) {
      closeMenu();
    }
  });
})();

/* ============================================================
   5. ACTIVE NAV LINK ON SCROLL
   ============================================================ */
(function initActiveNav() {
  const sections = document.querySelectorAll('section[id]');
  const navLinks = document.querySelectorAll('.nav__link');
  if (!sections.length || !navLinks.length) return;

  const offset = 140;

  const updateActive = () => {
    const scrollY = window.scrollY + offset;
    let current = '';

    sections.forEach((section) => {
      const top = section.offsetTop;
      const height = section.offsetHeight;
      if (scrollY >= top && scrollY < top + height) {
        current = section.getAttribute('id');
      }
    });

    // Если находимся в самом низу — активируем последнюю секцию
    if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 4) {
      const lastSection = sections[sections.length - 1];
      if (lastSection) current = lastSection.getAttribute('id');
    }

    navLinks.forEach((link) => {
      link.classList.toggle('active', link.getAttribute('href') === `#${current}`);
    });
  };

  window.addEventListener('scroll', updateActive, { passive: true });
  updateActive();
})();

/* ============================================================
   6. REVEAL ON SCROLL
   ============================================================ */
(function initReveal() {
  const elements = document.querySelectorAll('.reveal');
  if (!elements.length) return;

  if (!('IntersectionObserver' in window)) {
    elements.forEach((el) => el.classList.add('visible'));
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, {
    threshold: 0.1,
    rootMargin: '0px 0px -60px 0px'
  });

  elements.forEach((el, index) => {
    // Небольшая задержка для визуальной каскадности
    el.style.transitionDelay = `${(index % 6) * 0.06}s`;
    observer.observe(el);
  });
})();

/* ============================================================
   7. HERO SPARKLES
   ============================================================ */
(function initSparkles() {
  const container = document.getElementById('sparkles');
  if (!container) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const symbols = ['✦', '✧', '★', '☆', '✿', '❀', '❁'];
  const colors = ['#ff7eb3', '#d4af6a', '#c9a961', '#ff5c9d', '#f7e6c4'];

  const createSparkle = () => {
    const sparkle = document.createElement('span');
    sparkle.className = 'hero__sparkle';
    sparkle.textContent = symbols[Math.floor(Math.random() * symbols.length)];
    sparkle.style.left = `${Math.random() * 100}%`;
    sparkle.style.top = `${Math.random() * 100}%`;
    sparkle.style.color = colors[Math.floor(Math.random() * colors.length)];
    sparkle.style.fontSize = `${0.7 + Math.random() * 1.3}rem`;
    sparkle.style.animationDelay = `${Math.random() * 4}s`;
    sparkle.style.animationDuration = `${3 + Math.random() * 3}s`;

    container.appendChild(sparkle);

    setTimeout(() => {
      sparkle.remove();
    }, 8000);
  };

  // Создаём стартовые искры
  for (let i = 0; i < 12; i++) {
    setTimeout(createSparkle, i * 300);
  }

  // Постоянно добавляем новые
  setInterval(createSparkle, 1200);
})();

/* ============================================================
   8. PORTFOLIO / GALLERY FILTER
   ============================================================ */
(function initGalleryFilter() {
  const filters = document.querySelectorAll('.gallery__filter');
  const items = document.querySelectorAll('.gallery__item');
  if (!filters.length || !items.length) return;

  filters.forEach((filter) => {
    filter.addEventListener('click', () => {
      // Активный класс
      filters.forEach((f) => f.classList.remove('active'));
      filter.classList.add('active');

      const category = filter.dataset.filter;

      items.forEach((item, index) => {
        const itemCategory = item.dataset.category;
        const shouldShow = category === 'all' || itemCategory === category;

        if (shouldShow) {
          item.classList.remove('hidden');
          // Реанимация анимации
          item.style.animation = 'none';
          void item.offsetWidth;
          item.style.animation = `galleryIn 0.5s ease ${index * 0.04}s both`;
        } else {
          item.classList.add('hidden');
        }
      });
    });
  });

  // Добавляем keyframes динамически
  const style = document.createElement('style');
  style.textContent = `
    @keyframes galleryIn {
      from { opacity: 0; transform: translateY(20px) scale(0.95); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
  `;
  document.head.appendChild(style);
})();

/* ============================================================
   9. PRICING TABS
   ============================================================ */
(function initPricingTabs() {
  const tabs = document.querySelectorAll('.pricing__tab');
  const panels = document.querySelectorAll('.pricing__panel');
  if (!tabs.length || !panels.length) return;

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.tab;

      tabs.forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');

      panels.forEach((panel) => {
        if (panel.dataset.panel === target) {
          panel.classList.add('active');
        } else {
          panel.classList.remove('active');
        }
      });
    });
  });
})();

/* ============================================================
   10. REVIEWS SLIDER
   ============================================================ */
(function initReviewsSlider() {
  const track = document.getElementById('reviewsTrack');
  const dotsContainer = document.getElementById('reviewsDots');
  const prevBtn = document.getElementById('reviewPrev');
  const nextBtn = document.getElementById('reviewNext');
  if (!track || !dotsContainer) return;

  const slides = track.querySelectorAll('.review');
  if (!slides.length) return;

  let currentIndex = 0;
  let autoSlideTimer = null;
  const AUTO_INTERVAL = 6000;
  let isPaused = false;

  // Создаём точки
  slides.forEach((_, i) => {
    const dot = document.createElement('button');
    dot.className = 'reviews__dot';
    dot.setAttribute('aria-label', `Отзыв ${i + 1}`);
    if (i === 0) dot.classList.add('active');
    dot.addEventListener('click', () => {
      goTo(i);
      resetAutoSlide();
    });
    dotsContainer.appendChild(dot);
  });

  const dots = dotsContainer.querySelectorAll('.reviews__dot');

  function goTo(index) {
    currentIndex = index;
    if (currentIndex < 0) currentIndex = slides.length - 1;
    if (currentIndex >= slides.length) currentIndex = 0;

    track.style.transform = `translateX(-${currentIndex * 100}%)`;
    dots.forEach((d, i) => d.classList.toggle('active', i === currentIndex));
  }

  function next() {
    goTo(currentIndex + 1);
  }

  function prev() {
    goTo(currentIndex - 1);
  }

  function startAutoSlide() {
    stopAutoSlide();
    autoSlideTimer = setInterval(() => {
      if (!isPaused) next();
    }, AUTO_INTERVAL);
  }

  function stopAutoSlide() {
    if (autoSlideTimer) {
      clearInterval(autoSlideTimer);
      autoSlideTimer = null;
    }
  }

  function resetAutoSlide() {
    stopAutoSlide();
    startAutoSlide();
  }

  if (prevBtn) prevBtn.addEventListener('click', () => { prev(); resetAutoSlide(); });
  if (nextBtn) nextBtn.addEventListener('click', () => { next(); resetAutoSlide(); });

  // Пауза при наведении
  track.addEventListener('mouseenter', () => { isPaused = true; });
  track.addEventListener('mouseleave', () => { isPaused = false; });

  // Свайпы на тач-устройствах
  let touchStartX = 0;
  let touchStartY = 0;
  let isSwiping = false;

  track.addEventListener('touchstart', (e) => {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
    isSwiping = true;
    isPaused = true;
  }, { passive: true });

  track.addEventListener('touchend', (e) => {
    if (!isSwiping) return;
    isSwiping = false;
    isPaused = false;

    const dx = e.changedTouches[0].clientX - touchStartX;
    const dy = e.changedTouches[0].clientY - touchStartY;

    // Игнорируем, если движение больше вертикальное
    if (Math.abs(dy) > Math.abs(dx)) return;

    if (Math.abs(dx) > 50) {
      if (dx < 0) next();
      else prev();
      resetAutoSlide();
    }
  });

  // Клавиатура
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') { prev(); resetAutoSlide(); }
    if (e.key === 'ArrowRight') { next(); resetAutoSlide(); }
  });

  // Автослайд (с паузой, если слайдер вне вьюпорта)
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        startAutoSlide();
      } else {
        stopAutoSlide();
      }
    });
  }, { threshold: 0.3 });

  observer.observe(track);
})();

/* ============================================================
   11. FAQ ACCORDION
   ============================================================ */
(function initFaq() {
  const items = document.querySelectorAll('.faq__item');
  if (!items.length) return;

  items.forEach((item) => {
    const question = item.querySelector('.faq__question');
    if (!question) return;

    question.addEventListener('click', () => {
      const isOpen = item.classList.contains('open');

      // Закрываем все
      items.forEach((i) => i.classList.remove('open'));

      // Открываем текущий, если не был открыт
      if (!isOpen) {
        item.classList.add('open');
      }
    });
  });

  // Открываем первый по умолчанию
  if (items[0]) {
    items[0].classList.add('open');
  }
})();

/* ============================================================
   12. BOOKING FORM
   ============================================================ */
(function initBookingForm() {
  const form = document.getElementById('bookingForm');
  const success = document.getElementById('bookingSuccess');
  if (!form || !success) return;

  const phoneInput = form.querySelector('#b-phone');
  const dateInput = form.querySelector('#b-date');

  // Маска телефона
  if (phoneInput) {
    phoneInput.addEventListener('input', (e) => {
      let value = e.target.value.replace(/\D/g, '');
      if (value.startsWith('8')) value = '7' + value.slice(1);
      if (!value.startsWith('7') && value.length > 0) value = '7' + value;

      let formatted = '';
      if (value.length > 0) formatted = '+7';
      if (value.length > 1) formatted += ' (' + value.slice(1, 4);
      if (value.length >= 5) formatted += ') ' + value.slice(4, 7);
      if (value.length >= 8) formatted += '-' + value.slice(7, 9);
      if (value.length >= 10) formatted += '-' + value.slice(9, 11);

      e.target.value = formatted;
    });

    phoneInput.addEventListener('focus', (e) => {
      if (!e.target.value) e.target.value = '+7 (';
    });

    phoneInput.addEventListener('blur', (e) => {
      if (e.target.value === '+7 (' || e.target.value === '+7') {
        e.target.value = '';
      }
    });
  }

  // Минимальная дата — сегодня
  if (dateInput) {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    dateInput.min = `${yyyy}-${mm}-${dd}`;
  }

  // Отправка формы
  form.addEventListener('submit', (e) => {
    e.preventDefault();

    // Проверка чекбокса
    const checkbox = form.querySelector('input[type="checkbox"]');
    if (checkbox && !checkbox.checked) {
      checkbox.focus();
      shakeElement(checkbox.closest('.form__check'));
      return;
    }

    // Проверка полей
    const requiredFields = form.querySelectorAll('[required]');
    let valid = true;

    requiredFields.forEach((field) => {
      if (!field.value.trim()) {
        valid = false;
        shakeElement(field);
        field.style.borderColor = '#e8418a';
        setTimeout(() => {
          field.style.borderColor = '';
        }, 2000);
      }
    });

    if (!valid) return;

    const submitBtn = form.querySelector('button[type="submit"]');
    const originalHTML = submitBtn.innerHTML;

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span>Отправляем...</span>';

    // Имитация отправки на сервер
    setTimeout(() => {
      submitBtn.disabled = false;
      submitBtn.innerHTML = originalHTML;

      form.reset();

      success.classList.add('show');

      // Прокрутка к сообщению
      success.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

      setTimeout(() => {
        success.classList.remove('show');
      }, 6000);

      // Уведомление в консоль (для отладки)
      console.log('%c🎀 Заявка на запись отправлена!', 'color:#e8418a;font-size:14px;font-weight:bold;');
    }, 1400);
  });

  // Функция "встряхивания"
  function shakeElement(el) {
    el.style.animation = 'none';
    void el.offsetWidth;
    el.style.animation = 'shakeX 0.5s ease';
    setTimeout(() => {
      el.style.animation = '';
    }, 500);
  }

  // Добавляем keyframes для shake
  if (!document.getElementById('shakeKeyframes')) {
    const style = document.createElement('style');
    style.id = 'shakeKeyframes';
    style.textContent = `
      @keyframes shakeX {
        0%, 100% { transform: translateX(0); }
        20%, 60% { transform: translateX(-8px); }
        40%, 80% { transform: translateX(8px); }
      }
    `;
    document.head.appendChild(style);
  }
})();

/* ============================================================
   13. SUBSCRIBE FORM
   ============================================================ */
(function initSubscribeForm() {
  const form = document.getElementById('subscribeForm');
  const successMsg = document.getElementById('subscribeSuccess');
  if (!form) return;

  form.addEventListener('submit', (e) => {
    e.preventDefault();

    const input = form.querySelector('input');
    const button = form.querySelector('button');
    const email = input.value.trim();

    // Простая валидация
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      input.style.borderColor = '#e8418a';
      setTimeout(() => {
        input.style.borderColor = '';
      }, 2000);
      return;
    }

    const originalHTML = button.innerHTML;
    button.innerHTML = '✓';
    button.style.background = 'linear-gradient(135deg, #10b981, #059669)';

    input.value = '';

    if (successMsg) {
      successMsg.classList.add('show');
    }

    setTimeout(() => {
      button.innerHTML = originalHTML;
      button.style.background = '';
      if (successMsg) successMsg.classList.remove('show');
    }, 3500);
  });
})();

/* ============================================================
   14. SMOOTH SCROLL FOR ANCHORS
   ============================================================ */
(function initSmoothScroll() {
  const links = document.querySelectorAll('a[href^="#"]');

  links.forEach((link) => {
    link.addEventListener('click', (e) => {
      const href = link.getAttribute('href');
      if (!href || href === '#') return;

      const target = document.querySelector(href);
      if (!target) return;

      e.preventDefault();

      const header = document.getElementById('header');
      const headerHeight = header ? header.offsetHeight : 80;
      const targetPosition = target.getBoundingClientRect().top + window.scrollY - headerHeight - 20;

      window.scrollTo({
        top: targetPosition,
        behavior: 'smooth'
      });

      // Обновляем URL без прыжка
      if (history.pushState) {
        history.pushState(null, null, href);
      }
    });
  });
})();

/* ============================================================
   15. PARALLAX EFFECT ON HERO BLOBS
   ============================================================ */
(function initParallax() {
  if (window.matchMedia('(max-width: 1024px)').matches) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const blobs = document.querySelectorAll('.hero__blob');
  if (!blobs.length) return;

  let ticking = false;
  let mouseX = window.innerWidth / 2;
  let mouseY = window.innerHeight / 2;

  document.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;

    if (!ticking) {
      requestAnimationFrame(updateParallax);
      ticking = true;
    }
  });

  function updateParallax() {
    const offsetX = (mouseX / window.innerWidth - 0.5) * 2;
    const offsetY = (mouseY / window.innerHeight - 0.5) * 2;

    blobs.forEach((blob, i) => {
      const strength = (i + 1) * 12;
      const x = offsetX * strength;
      const y = offsetY * strength;
      blob.style.transform = `translate(${x}px, ${y}px)`;
    });

    ticking = false;
  }
})();

/* ============================================================
   16. TILT EFFECT ON CARDS
   ============================================================ */
(function initTilt() {
  if (window.matchMedia('(max-width: 1024px)').matches) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const cards = document.querySelectorAll('.service, .master, .hero__card--main');

  cards.forEach((card) => {
    card.addEventListener('mousemove', (e) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const centerX = rect.width / 2;
      const centerY = rect.height / 2;

      const rotateX = ((y - centerY) / centerY) * -4;
      const rotateY = ((x - centerX) / centerX) * 4;

      card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-6px)`;
    });

    card.addEventListener('mouseleave', () => {
      card.style.transform = '';
    });
  });
})();

/* ============================================================
   17. BUTTON RIPPLE EFFECT
   ============================================================ */
(function initRipple() {
  const buttons = document.querySelectorAll('.btn');

  buttons.forEach((btn) => {
    btn.addEventListener('click', function (e) {
      // Не срабатывает, если есть анимация предпочтений
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

      const rect = this.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);
      const x = e.clientX - rect.left - size / 2;
      const y = e.clientY - rect.top - size / 2;

      const ripple = document.createElement('span');
      ripple.style.cssText = `
        position: absolute;
        width: ${size}px;
        height: ${size}px;
        left: ${x}px;
        top: ${y}px;
        background: rgba(255, 255, 255, 0.4);
        border-radius: 50%;
        transform: scale(0);
        animation: rippleEffect 0.7s ease-out;
        pointer-events: none;
        z-index: 1;
      `;

      this.appendChild(ripple);

      setTimeout(() => {
        ripple.remove();
      }, 700);
    });
  });

  // Keyframes для ripple
  if (!document.getElementById('rippleKeyframes')) {
    const style = document.createElement('style');
    style.id = 'rippleKeyframes';
    style.textContent = `
      @keyframes rippleEffect {
        to {
          transform: scale(2.5);
          opacity: 0;
        }
      }
    `;
    document.head.appendChild(style);
  }
})();

/* ============================================================
   18. COUNTER ANIMATION (если появятся счётчики)
   ============================================================ */
(function initCounters() {
  const counters = document.querySelectorAll('[data-count]');
  if (!counters.length) return;

  const animateCounter = (el, target, duration = 1800) => {
    const start = performance.now();
    const isFloat = String(target).includes('.');

    const step = (now) => {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const value = target * eased;

      el.textContent = isFloat ? value.toFixed(1) : Math.floor(value).toLocaleString('ru-RU');

      if (progress < 1) {
        requestAnimationFrame(step);
      } else {
        el.textContent = isFloat ? target.toFixed(1) : target.toLocaleString('ru-RU');
      }
    };

    requestAnimationFrame(step);
  };

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const target = parseFloat(entry.target.dataset.count);
        animateCounter(entry.target, target);
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.5 });

  counters.forEach((counter) => observer.observe(counter));
})();

/* ============================================================
   19. LAZY LOADING IMAGES
   ============================================================ */
(function initLazyImages() {
  if (!('loading' in HTMLImageElement.prototype)) return;

  const images = document.querySelectorAll('img:not([loading])');
  images.forEach((img) => img.setAttribute('loading', 'lazy'));
})();

/* ============================================================
   20. PREVENT SCROLL DURING PRELOADER (уже реализовано выше)
   + Блокируем скролл при открытии мобильного меню (тоже выше)
   ============================================================ */

/* ============================================================
   21. EASTER EGG: KONAMI CODE 🎀
   ============================================================ */
(function initEasterEgg() {
  const konamiCode = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a'];
  let position = 0;

  document.addEventListener('keydown', (e) => {
    if (e.key === konamiCode[position] || e.key.toLowerCase() === konamiCode[position]) {
      position++;
      if (position === konamiCode.length) {
        activateEasterEgg();
        position = 0;
      }
    } else {
      position = 0;
    }
  });

  function activateEasterEgg() {
    console.log('%c🎀🎀🎀 HELLO KITTY MODE ACTIVATED! 🎀🎀🎀', 'color:#ff1493;font-size:20px;font-weight:bold;text-shadow:2px 2px 4px rgba(0,0,0,0.2);');

    // Создаём дождь из бантиков
    const bowRain = document.createElement('div');
    bowRain.style.cssText = `
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 10000;
      overflow: hidden;
    `;

    for (let i = 0; i < 60; i++) {
      const bow = document.createElement('span');
      bow.textContent = '🎀';
      bow.style.cssText = `
        position: absolute;
        left: ${Math.random() * 100}%;
        top: -60px;
        font-size: ${20 + Math.random() * 40}px;
        animation: bowFall ${3 + Math.random() * 4}s linear ${Math.random() * 2}s forwards;
        opacity: 0.9;
      `;
      bowRain.appendChild(bow);
    }

    const style = document.createElement('style');
    style.textContent = `
      @keyframes bowFall {
        to {
          transform: translateY(110vh) rotate(${Math.random() * 720 - 360}deg);
          opacity: 0;
        }
      }
    `;

    document.head.appendChild(style);
    document.body.appendChild(bowRain);

    // Плавный розовый оттенок на секунду
    document.body.style.transition = 'filter 0.5s ease';
    document.body.style.filter = 'hue-rotate(20deg) saturate(1.3)';
    setTimeout(() => {
      document.body.style.filter = '';
    }, 2000);

    setTimeout(() => {
      bowRain.remove();
      style.remove();
    }, 9000);
  }
})();

/* ============================================================
   22. CONSOLE SIGNATURE
   ============================================================ */
(function initConsoleSignature() {
  const styles = {
    title: 'color:#e8418a;font-family:Georgia,serif;font-size:22px;font-weight:bold;',
    sub: 'color:#d4af6a;font-size:12px;letter-spacing:3px;font-weight:600;',
    text: 'color:#52525e;font-size:12px;',
    hint: 'color:#ff5c9d;font-size:11px;font-style:italic;'
  };

  console.log('%c🎀 PINK ÉLITE', styles.title);
  console.log('%cLUXURY NAIL STUDIO', styles.sub);
  console.log('%cПремиальный нейл-салон: Hello Kitty × Chanel × Dior', styles.text);
  console.log('%c💡 Попробуйте код Konami: ↑↑↓↓←→←→BA', styles.hint);
  console.log('%cСайт разработан с 💖 в 2025', styles.text);
})();

/* ============================================================
   23. WINDOW RESIZE HANDLER
   ============================================================ */
(function initResizeHandler() {
  let resizeTimer;

  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      // Закрываем мобильное меню при переходе на десктоп
      if (window.innerWidth > 1024) {
        const nav = document.getElementById('nav');
        const burger = document.getElementById('burger');

        if (nav && nav.classList.contains('open')) {
          nav.classList.remove('open');
          if (burger) burger.classList.remove('active');
          document.body.style.overflow = '';
        }
      }

      // Пересчёт активных ссылок
      window.dispatchEvent(new Event('scroll'));
    }, 200);
  });
})();

/* ============================================================
   24. HANDLE VISIBILITY CHANGE
   ============================================================ */
(function initVisibilityHandler() {
  let wasHidden = false;

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      wasHidden = true;
    } else if (wasHidden) {
      // При возврате на страницу — обновляем состояние
      window.dispatchEvent(new Event('scroll'));
      wasHidden = false;
    }
  });
})();

/* ============================================================
   25. PERFORMANCE: prefetch on hover
   ============================================================ */
(function initPrefetch() {
  const internalLinks = document.querySelectorAll('a[href^="#"]');

  internalLinks.forEach((link) => {
    link.addEventListener('mouseenter', () => {
      // Просто подготавливаем — плавная прокрутка уже встроена
      const target = document.querySelector(link.getAttribute('href'));
      if (target) {
        // Мягкий pre-render (touch стилей)
        target.style.willChange = 'transform';
        setTimeout(() => {
          target.style.willChange = '';
        }, 500);
      }
    });
  });
})();

/* ============================================================
   END OF SCRIPT
   ============================================================ */