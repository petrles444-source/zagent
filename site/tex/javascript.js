/* ========== HEADER SCROLL ========== */
const header = document.getElementById('header');
const toTop = document.getElementById('toTop');

window.addEventListener('scroll', () => {
  const y = window.scrollY;
  header.classList.toggle('scrolled', y > 40);
  toTop.classList.toggle('show', y > 600);
});

toTop.addEventListener('click', () => {
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

/* ========== BURGER MENU ========== */
const burger = document.getElementById('burger');
const nav = document.getElementById('nav');
const navLinks = document.querySelectorAll('.nav__link');

burger.addEventListener('click', () => {
  burger.classList.toggle('active');
  nav.classList.toggle('open');
  document.body.style.overflow = nav.classList.contains('open') ? 'hidden' : '';
});

navLinks.forEach(link => {
  link.addEventListener('click', () => {
    burger.classList.remove('active');
    nav.classList.remove('open');
    document.body.style.overflow = '';
  });
});

/* ========== ACTIVE NAV LINK ON SCROLL ========== */
const sections = document.querySelectorAll('section[id]');

function updateActiveNav() {
  const scrollPos = window.scrollY + 120;
  sections.forEach(section => {
    const top = section.offsetTop;
    const height = section.offsetHeight;
    const id = section.getAttribute('id');
    const link = document.querySelector(`.nav__link[href="#${id}"]`);
    if (!link) return;
    if (scrollPos >= top && scrollPos < top + height) {
      navLinks.forEach(l => l.classList.remove('active'));
      link.classList.add('active');
    }
  });
}
window.addEventListener('scroll', updateActiveNav);

/* ========== REVEAL ON SCROLL ========== */
const revealElements = document.querySelectorAll('.reveal');

const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry, index) => {
    if (entry.isIntersecting) {
      setTimeout(() => {
        entry.target.classList.add('visible');
      }, index * 60);
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.12, rootMargin: '0px 0px -60px 0px' });

revealElements.forEach(el => revealObserver.observe(el));

/* ========== COUNTER ANIMATION ========== */
const counters = document.querySelectorAll('[data-count]');
let countersStarted = false;

function animateCounters() {
  counters.forEach(counter => {
    const target = +counter.dataset.count;
    const duration = 2000;
    const start = performance.now();

    function step(now) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      counter.textContent = Math.floor(eased * target);
      if (progress < 1) requestAnimationFrame(step);
      else counter.textContent = target;
    }
    requestAnimationFrame(step);
  });
}

const statsSection = document.querySelector('.hero__stats');
if (statsSection) {
  const counterObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting && !countersStarted) {
        countersStarted = true;
        animateCounters();
        counterObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.4 });
  counterObserver.observe(statsSection);
}

/* ========== PORTFOLIO FILTER ========== */
const filterButtons = document.querySelectorAll('.filter');
const projects = document.querySelectorAll('.project');

filterButtons.forEach(btn => {
  btn.addEventListener('click', () => {
    filterButtons.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    const filter = btn.dataset.filter;

    projects.forEach(project => {
      const category = project.dataset.category;
      const show = filter === 'all' || filter === category;

      if (show) {
        project.classList.remove('hidden');
        project.style.animation = 'none';
        void project.offsetWidth;
        project.style.animation = 'fadeIn 0.5s ease';
      } else {
        project.classList.add('hidden');
      }
    });
  });
});

/* ========== TESTIMONIALS SLIDER ========== */
const track = document.getElementById('testimonialsTrack');
const dotsContainer = document.getElementById('testimonialsDots');

if (track && dotsContainer) {
  const slides = track.querySelectorAll('.testimonial');
  let currentIndex = 0;
  let autoSlide;

  slides.forEach((_, i) => {
    const dot = document.createElement('button');
    dot.setAttribute('aria-label', `Отзыв ${i + 1}`);
    if (i === 0) dot.classList.add('active');
    dot.addEventListener('click', () => goToSlide(i));
    dotsContainer.appendChild(dot);
  });

  const dots = dotsContainer.querySelectorAll('button');

  function goToSlide(index) {
    currentIndex = index;
    track.style.transform = `translateX(-${index * 100}%)`;
    dots.forEach((d, i) => d.classList.toggle('active', i === index));
    resetAutoSlide();
  }

  function nextSlide() {
    currentIndex = (currentIndex + 1) % slides.length;
    goToSlide(currentIndex);
  }

  function startAutoSlide() {
    autoSlide = setInterval(nextSlide, 6000);
  }

  function resetAutoSlide() {
    clearInterval(autoSlide);
    startAutoSlide();
  }

  startAutoSlide();

  // Swipe support
  let startX = 0;
  let isDragging = false;

  track.addEventListener('touchstart', (e) => {
    startX = e.touches[0].clientX;
    isDragging = true;
    clearInterval(autoSlide);
  }, { passive: true });

  track.addEventListener('touchend', (e) => {
    if (!isDragging) return;
    isDragging = false;
    const diff = e.changedTouches[0].clientX - startX;
    if (Math.abs(diff) > 50) {
      if (diff < 0) currentIndex = (currentIndex + 1) % slides.length;
      else currentIndex = (currentIndex - 1 + slides.length) % slides.length;
      goToSlide(currentIndex);
    } else {
      startAutoSlide();
    }
  });
}

/* ========== FAQ ACCORDION ========== */
const faqItems = document.querySelectorAll('.faq__item');

faqItems.forEach(item => {
  const question = item.querySelector('.faq__question');
  question.addEventListener('click', () => {
    const isOpen = item.classList.contains('open');
    faqItems.forEach(i => i.classList.remove('open'));
    if (!isOpen) item.classList.add('open');
  });
});

/* ========== CONTACT FORM ========== */
const contactForm = document.getElementById('contactForm');
const formSuccess = document.getElementById('formSuccess');

if (contactForm) {
  contactForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const submitBtn = contactForm.querySelector('button[type="submit"]');
    const originalText = submitBtn.textContent;

    submitBtn.textContent = 'Отправка...';
    submitBtn.disabled = true;

    setTimeout(() => {
      submitBtn.textContent = originalText;
      submitBtn.disabled = false;
      formSuccess.classList.add('show');
      contactForm.reset();

      setTimeout(() => formSuccess.classList.remove('show'), 5000);
    }, 1200);
  });
}

/* ========== SUBSCRIBE FORM ========== */
const subscribeForm = document.getElementById('subscribeForm');

if (subscribeForm) {
  subscribeForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const input = subscribeForm.querySelector('input');
    const button = subscribeForm.querySelector('button');
    const originalText = button.textContent;

    button.textContent = '✓';
    input.value = '';
    input.placeholder = 'Спасибо за подписку!';

    setTimeout(() => {
      button.textContent = originalText;
      input.placeholder = 'Ваш email';
    }, 3000);
  });
}

/* ========== SMOOTH SCROLL FOR ANCHORS ========== */
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function (e) {
    const targetId = this.getAttribute('href');
    if (targetId === '#') return;
    const target = document.querySelector(targetId);
    if (!target) return;

    e.preventDefault();
    const offset = 80;
    const top = target.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo({ top, behavior: 'smooth' });
  });
});

/* ========== PARALLAX ORBS ========== */
const orbs = document.querySelectorAll('.hero__orb');

if (window.matchMedia('(min-width: 769px)').matches && orbs.length) {
  window.addEventListener('mousemove', (e) => {
    const x = (e.clientX / window.innerWidth - 0.5) * 30;
    const y = (e.clientY / window.innerHeight - 0.5) * 30;

    orbs.forEach((orb, i) => {
      const factor = (i + 1) * 0.5;
      orb.style.transform = `translate(${x * factor}px, ${y * factor}px)`;
    });
  });
}

/* ========== CODE CARD TYPING EFFECT ========== */
const codeCard = document.querySelector('.code-card__body code');

if (codeCard) {
  const html = codeCard.innerHTML;
  const plainText = codeCard.textContent;

  const codeObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        codeCard.style.opacity = '0';
        setTimeout(() => {
          codeCard.style.transition = 'opacity 0.8s ease';
          codeCard.style.opacity = '1';
        }, 200);
        codeObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.3 });

  codeObserver.observe(codeCard);
}

/* ========== BUTTON RIPPLE ========== */
document.querySelectorAll('.btn--primary').forEach(btn => {
  btn.addEventListener('click', function (e) {
    const rect = this.getBoundingClientRect();
    const ripple = document.createElement('span');
    const size = Math.max(rect.width, rect.height);
    const x = e.clientX - rect.left - size / 2;
    const y = e.clientY - rect.top - size / 2;

    ripple.style.cssText = `
      position: absolute;
      width: ${size}px;
      height: ${size}px;
      left: ${x}px;
      top: ${y}px;
      background: rgba(255,255,255,0.35);
      border-radius: 50%;
      transform: scale(0);
      animation: ripple 0.6s ease-out;
      pointer-events: none;
    `;

    this.appendChild(ripple);
    setTimeout(() => ripple.remove(), 600);
  });
});

const rippleStyle = document.createElement('style');
rippleStyle.textContent = `
  @keyframes ripple {
    to { transform: scale(2.5); opacity: 0; }
  }
`;
document.head.appendChild(rippleStyle);

/* ========== LAZY IMAGE FALLBACK (для будущих img) ========== */
if ('loading' in HTMLImageElement.prototype) {
  document.querySelectorAll('img').forEach(img => {
    if (!img.hasAttribute('loading')) img.setAttribute('loading', 'lazy');
  });
}

/* ========== CONSOLE SIGNATURE ========== */
console.log(
  '%c◆ NovaTech %c— Создаём цифровое будущее 🚀',
  'color:#6366f1;font-size:16px;font-weight:800;',
  'color:#9a9ab0;font-size:13px;'
);