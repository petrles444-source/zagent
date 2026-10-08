// ... (предыдущий код для header и fade-in остается) ...

document.addEventListener('DOMContentLoaded', () => {
    
    // 1. Эффект "липкой" шапки при скролле
    const header = document.getElementById('header');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 50) {
            header.classList.add('scrolled');
        } else {
            header.classList.remove('scrolled');
        }
    });

    // 2. Плавное появление секций при скролле
    const fadeElements = document.querySelectorAll('.fade-in');
    const appearOptions = { threshold: 0.15, rootMargin: "0px 0px -50px 0px" };
    const appearOnScroll = new IntersectionObserver(function(entries, appearOnScroll) {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            entry.target.classList.add('visible');
            appearOnScroll.unobserve(entry.target);
        });
    }, appearOptions);
    fadeElements.forEach(element => appearOnScroll.observe(element));

    // 3. Плавный скролл для навигации
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const targetId = this.getAttribute('href');
            if (targetId === '#') return;
            const targetElement = document.querySelector(targetId);
            if (targetElement) {
                targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    });

    // 4. Логика для FAQ (Аккордеон)
    const faqItems = document.querySelectorAll('.faq-item');
    faqItems.forEach(item => {
        const question = item.querySelector('.faq-question');
        question.addEventListener('click', () => {
            // Закрываем все остальные открытые вопросы
            faqItems.forEach(otherItem => {
                if (otherItem !== item) {
                    otherItem.classList.remove('active');
                }
            });
            // Переключаем текущий
            item.classList.toggle('active');
        });
    });

    // 5. Логика для Модального окна
    const modal = document.getElementById('modal');
    const openButtons = document.querySelectorAll('.open-modal');
    const closeButton = document.getElementById('modal-close');
    const modalForm = document.getElementById('modal-form');

    // Открытие
    openButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            modal.classList.add('active');
            document.body.style.overflow = 'hidden'; // Блокируем скролл фона
        });
    });

    // Закрытие по крестику
    closeButton.addEventListener('click', () => {
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
    });

    // Закрытие по клику вне окна
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('active');
            document.body.style.overflow = 'auto';
        }
    });

    // Обработка формы (заглушка)
    modalForm.addEventListener('submit', (e) => {
        e.preventDefault();
        alert('Спасибо! Ваша заявка отправлена. Мы свяжемся с вами в ближайшее время.');
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
        modalForm.reset();
    });
});