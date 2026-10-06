// saas-minimal — проверка формы без сборки.
//
// Что здесь показывает:
//   - проверка ДО отправки, а не после;
//   - ошибки рядом с полем, а не одним блоком;
//   - aria-invalid и role="alert", чтобы сообщение прочитал скринридер;
//   - форма не уходит, даже если бэкенда нет: fetch ловится и сообщается.

const form = document.getElementById('leadForm');
const email = document.getElementById('email');
const team = document.getElementById('team');
const submit = document.getElementById('leadSubmit');
const done = document.getElementById('leadDone');

const errors = {
  email: document.getElementById('emailErr'),
  team: document.getElementById('teamErr'),
};

// Намеренно строгий шаблон: встроенный type="email" пропускает "a@b", который
// почтой не является.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[a-z]{2,}$/i;

function setError(input, node, message) {
  node.textContent = message;
  if (message) {
    input.setAttribute('aria-invalid', 'true');
  } else {
    input.removeAttribute('aria-invalid');
  }
  return !message;
}

function validate() {
  const value = email.value.trim();
  let ok = true;

  if (!value) {
    ok = setError(email, errors.email, 'Укажите почту.') && ok;
  } else if (!EMAIL_RE.test(value)) {
    ok = setError(email, errors.email, 'Похоже, в адресе опечатка.') && ok;
  } else {
    ok = setError(email, errors.email, '') && ok;
  }

  const size = team.value.trim();
  if (size) {
    const num = Number(size);
    if (!Number.isInteger(num) || num < 1 || num > 1000) {
      ok = setError(team, errors.team, 'От 1 до 1000.') && ok;
    } else {
      ok = setError(team, errors.team, '') && ok;
    }
  } else {
    ok = setError(team, errors.team, '') && ok;
  }

  return ok;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  done.hidden = true;

  if (!validate()) {
    // Фокус на первое проблемное поле: иначе на узком экране сообщение
    // окажется за пределами видимой области.
    form.querySelector('[aria-invalid="true"]')?.focus();
    return;
  }

  submit.disabled = true;
  submit.textContent = 'Отправляем…';

  try {
    const response = await fetch('/api/lead', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.value.trim(), team: team.value.trim() || null }),
    });
    if (!response.ok) {
      throw new Error('сервер ответил ' + response.status);
    }
    form.reset();
    done.hidden = false;
  } catch (err) {
    // Заглушки нет — здесь честно говорим, что запрос не прошёл.
    setError(email, errors.email, 'Не удалось отправить: ' + err.message);
  } finally {
    submit.disabled = false;
    submit.textContent = 'Отправить';
  }
});

// Проверка на лету, но не мешает печатать: ошибка появляется после blur.
email.addEventListener('blur', validate);
team.addEventListener('blur', validate);