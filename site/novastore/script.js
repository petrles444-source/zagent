// Умная тема с сохранением
class ThemeManager {
    constructor() {
        this.toggle = document.getElementById('themeToggle');
        this.icon = this.toggle.querySelector('.theme-icon');
        this.init();
    }

    init() {
        const saved = localStorage.getItem('theme') || 
                     (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        this.set(saved);
        
        this.toggle.addEventListener('click', () => {
            const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
            this.set(next);
            localStorage.setItem('theme', next);
        });
    }

    set(theme) {
        document.documentElement.dataset.theme = theme;
        this.icon.textContent = theme === 'dark' ? '☀️' : '🌙';
    }
}

// Умная навигация
class Navigation {
    constructor() {
        this.burger = document.getElementById('burger');
        this.links = document.getElementById('navLinks');
        this.header = document.getElementById('header');
        this.init();
    }

    init() {
        this.burger.addEventListener('click', () => this.toggleMenu());
        
        document.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const target = link.getAttribute('href').slice(1);
                this.scrollTo(target);
                this.closeMenu();
            });
        });

        window.addEventListener('scroll', () => this.handleScroll(), { passive: true });
        this.highlightActive();
    }

    toggleMenu() {
        this.links.classList.toggle('active');
        this.burger.classList.toggle('active');
    }

    closeMenu() {
        this.links.classList.remove('active');
        this.burger.classList.remove('active');
    }

    scrollTo(id) {
        document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
    }

    handleScroll() {
        this.header.style.background = scrollY > 100 
            ? 'var(--bg-secondary)' 
            : 'var(--bg-primary)';
    }

    highlightActive() {
        const sections = document.querySelectorAll('section[id]');
        const navLinks = document.querySelectorAll('.nav-link');
        
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    navLinks.forEach(link => {
                        link.classList.toggle('active', 
                            link.getAttribute('href') === `#${entry.target.id}`);
                    });
                }
            });
        }, { threshold: 0.5 });
        
        sections.forEach(section => observer.observe(section));
    }
}

// Анимированные счетчики
class Counter {
    constructor() {
        this.counters = document.querySelectorAll('.stat-number');
        this.init();
    }

    init() {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    this.animate(entry.target);
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.5 });

        this.counters.forEach(counter => observer.observe(counter));
    }

    animate(element) {
        const target = +element.dataset.target;
        const duration = 2000;
        const start = performance.now();

        const tick = (now) => {
            const progress = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            element.textContent = Math.round(target * eased);
            
            if (progress < 1) requestAnimationFrame(tick);
        };

        requestAnimationFrame(tick);
    }
}

// Умная форма с валидацией
class SmartForm {
    constructor() {
        this.form = document.getElementById('contactForm');
        this.submitBtn = this.form.querySelector('.submit-btn');
        this.init();
    }

    init() {
        this.form.addEventListener('submit', (e) => this.handleSubmit(e));
        
        // Живая валидация
        ['name', 'email', 'message'].forEach(id => {
            const field = document.getElementById(id);
            field.addEventListener('input', () => this.validateField(field));
            field.addEventListener('blur', () => this.validateField(field));
        });
    }

    validateField(field) {
        const value = field.value.trim();
        const error = document.getElementById(`${field.id}Error`);
        let message = '';

        switch(field.id) {
            case 'name':
                if (value.length < 2) message = 'Имя должно быть минимум 2 символа';
                break;
            case 'email':
                if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) 
                    message = 'Введите корректный email';
                break;
            case 'message':
                if (value.length < 10) message = 'Сообщение минимум 10 символов';
                break;
        }

        error.textContent = message;
        field.style.borderColor = message ? '#ef4444' : 'var(--border)';
        return !message;
    }

    async handleSubmit(e) {
        e.preventDefault();
        
        const isValid = ['name', 'email', 'message']
            .map(id => this.validateField(document.getElementById(id)))
            .every(Boolean);

        if (!isValid) return;

        this.setLoading(true);

        // Имитация отправки
        await new Promise(resolve => setTimeout(resolve, 1500));

        this.setLoading(false);
        this.showSuccess();
        this.form.reset();
    }

    setLoading(loading) {
        this.submitBtn.disabled = loading;
        this.submitBtn.querySelector('.btn-text').textContent = 
            loading ? 'Отправка...' : 'Отправить';
        this.submitBtn.querySelector('.btn-loader').style.display = 
            loading ? 'inline' : 'none';
    }

    showSuccess() {
        const btn = this.submitBtn;
        const original = btn.querySelector('.btn-text').textContent;
        
        btn.querySelector('.btn-text').textContent = '✓ Отправлено';
        btn.style.background = '#10b981';
        
        setTimeout(() => {
            btn.querySelector('.btn-text').textContent = original;
            btn.style.background = '';
        }, 3000);
    }
}

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    new ThemeManager();
    new Navigation();
    new Counter();
    new SmartForm();
});

// Глобальная функция для кнопки в hero
function scrollToSection(id) {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
}
