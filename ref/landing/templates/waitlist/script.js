// waitlist — проверка и отправка.
//
// Минимальный набор: одно поле, одна кнопка, одно сообщение об ошибке.
// Показываем ошибку после blur, а не на каждый символ — иначе сообщение
// мигает, пока человек ещё печатает.

const form = document.getElementById('waitlist');
const input = document.getElementById('email');
const err = document.getElementById('err');
const go = document.getElementById('go');
const ok = document.getElementById('ok');

// Встроенная проверка type="email" пропускает "a@b", поэтому свой шаблон.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[a-z]{2,}$/i;

function validate() {
  const value = input.value.trim();
  let message = '';
  if (!value) {
    message = 'Укажите почту.';
  } else if (!EMAIL_RE.test(value)) {
    message = 'Похоже, в адресе опечатка.';
  }
  err.textContent = message;
  if (message) {
    input.setAttribute('aria-invalid', 'true');
  } else {
    input.removeAttribute('aria-invalid');
  }
  return !message;
}

input.addEventListener('blur', validate);

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  ok.hidden = true;

  if (!validate()) {
    input.focus();
    return;
  }

  // Кнопка блокируется: без этого один человек отправит три одинаковых заявки.
  go.disabled = true;
  go.textContent = 'Отправляем…';

  try {
    const response = await fetch('/api/lead', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: input.value.trim() }),
    });
    if (!response.ok) {
      throw new Error('сервер ответил ' + response.status);
    }
    form.reset();
    ok.hidden = false;
  } catch (problem) {
    err.textContent = 'Не удалось отправить: ' + problem.message;
    input.setAttribute('aria-invalid', 'true');
  } finally {
    go.disabled = false;
    go.textContent = 'Сообщить мне';
  }
});