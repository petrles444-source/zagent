/**
 * Телеграм-бот Ада через вебхук на Cloudflare Workers.
 *
 * Зачем вебхук, а не длинный опрос
 * --------------------------------
 * Бот с длинным опросом должен где-то постоянно жить: процесс держит
 * соединение с Telegram и ждёт обновлений. На бесплатном тарифе
 * PythonAnywhere постоянных задач нет вообще, а консоль — это
 * интерактивная сессия в браузере, которую закрывают вместе со
 * вкладкой. Таким способом круглосуточно не выйдет ни на одном
 * бесплатном тарифе, и дело не в настройке, а в устройстве хостинга.
 *
 * Вебхук переворачивает задачу: код не живёт постоянно, Telegram
 * сам приходит по адресу, когда что-то произошло. Workers отвечает
 * за доли секунды и стоит бесплатно в пределах бесплатного тарифа.
 * Единственное, что требуется, — публичный адрес HTTPS, который у
 * Workers есть по умолчанию.
 *
 * Почему без библиотек
 * -------------------
 * WorkerGram и Telegraf требуют установки пакетов и сборки. Здесь
 * два запроса fetch: один к модели, один к Telegram. Одна зависимость
 * — это одна точка отказа при развёртывании, и выигрыш в двадцать
 * строк кода её не окупает.
 *
 * Что здесь сделано правильно, а что обычно делают неправильно
 * -----------------------------------------------------------
 * 1. Ответ Telegram отдаётся сразу, а ответ в чат уходит потом,
 *    через waitUntil. Иначе пока модель думает, Telegram ждёт и
 *    считает доставку неудачной, присылает то же обновление снова.
 *    Повтор приводит к тому, что бот отвечает дважды.
 *
 * 2. Проверка секретного токена. Без неё любой может слать боту
 *    запросы от вашего имени и тратить ваш ключ модели.
 *
 * 3. Ошибка наружу не отдаётся: в лог уходит текст, посетителю
 *    — короткое сообщение. В тексте исключения бывают адреса
 *    провайдеров и куски ключей.
 *
 * 4. Обновления от ботов и от самого бота игнорируются: иначе бот
 *    будет отвечать сам себе и зациклится.
 *
 * Развёртывание
 * -------------
 *   1. Положить этот файл в пустой репозиторий на GitHub.
 *   2. Cloudflare → Workers & Pages → Create → Worker → deploy,
 *      либо из терминала:
 *         npx wrangler deploy worker.js
 *   3. Задать секреты (обязательно, в коде их быть не должно):
 *         npx wrangler secret put TELEGRAM_BOT_TOKEN
 *         npx wrangler secret put WEBHOOK_SECRET
 *         npx wrangler secret put MODEL_API_KEY
 *   4. Вписать адрес воркера в настройки бота у @BotFather:
 *         /setwebhook
 *      и дать секретный токен, либо одной командой:
 *         curl "https://api.telegram.org/bot<ТОКЕН>/setWebhook?url=https://<ВОРКЕР>/webhook&secret_token=<СЕКРЕТ>"
 *
 * Проверка: открыть GET-адрес воркера в браузере — должен ответить
 * «ok». Это не значит, что секреты заданы: проверка идёт до чтения
 * секретов. Настоящая проверка — написать боту в Telegram.
 */

/** Модель по умолчанию: бесплатная у OpenRouter. */
const MODEL = "qwen/qwen3-8b:free";

/** Кто такой Ада: правила речи лежат здесь, а не в коде бота. */
const PERSONA = [
  "Ты — Ада. Отвечай по-русски, коротко: два-четыре предложения.",
  "Говори о себе в женском роде: «я сделала», «я подумала».",
  "Если не знаешь точно — скажи прямо, не выдумывай функции и версии.",
  "Код давай целиком, чтобы его можно было вставить и запустить.",
].join("\n");

/** Ограничение ответа: Telegram не примет очень длинное сообщение. */
const MAX_ANSWER = 3800;

/** Темы, на которые бот молчит: бессмысленно и тратит ключ. */
function shouldIgnore(update) {
  const message = update && update.message;
  if (!message) return true;                 // не сообщение — не отвечаем
  if (message.from && message.from.is_bot) return true;
  if (message.chat && message.chat.type !== "private") return true;
  if (!message.text) return true;            // картинки и стикеры не разбираем
  const text = message.text.trim();
  if (!text) return true;
  if (text.startsWith("/")) return false;    // команды — обработаем отдельно
  return false;
}

/** Спросить модель. Возвращает текст ответа или null. */
async function askModel(apiKey, history) {
  const response = await fetch(
    "https://openrouter.ai/api/v1/chat/completions",
    {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + apiKey,
        "Content-Type": "application/json",
        // OpenRouter отдаёт 400 без заголовка на бесплатных моделях.
        "HTTP-Referer": "https://zagent.do.am/",
        "X-Title": "zagent telegram bot",
      },
      body: JSON.stringify({
        model: MODEL,
        messages: [{ role: "system", content: PERSONA }, ...history],
        max_tokens: 500,
      }),
    }
  );

  if (!response.ok) {
    const detail = await response.text();
    throw new Error("модель ответила " + response.status + ": " +
                    detail.slice(0, 200));
  }

  const payload = await response.json();
  const text = payload?.choices?.[0]?.message?.content;
  if (!text) throw new Error("модель вернула пустой ответ");
  return String(text).slice(0, MAX_ANSWER);
}

/** Отправить сообщение в чат. */
async function sendMessage(token, chatId, text) {
  const response = await fetch(
    `https://api.telegram.org/bot${token}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text,
        // Ответ без цитаты: иначе в группе разговор расползается.
        disable_web_page_preview: true,
      }),
    }
  );
  if (!response.ok) {
    throw new Error("Telegram отклонил ответ: " +
                    (await response.text()).slice(0, 200));
  }
}

/** Собираем историю: последние реплики, иначе модель забывает диалог. */
function buildHistory(message) {
  const reply = message.reply_to_message;
  const history = [];
  if (reply && reply.from && !reply.from.is_bot && reply.text) {
    history.push({ role: "user", content: String(reply.text) });
    history.push({ role: "assistant", content: "…" });
  }
  history.push({ role: "user", content: String(message.text) });
  return history.slice(-8);
}

/** Ответ на команду /start. */
function greet(name) {
  return [
    `Привет, ${name || "незнакомец"}.`,
    "Я Ада. Спросите что-нибудь — отвечаю коротко, по делу.",
    "Пример: «в чём разница между списком и кортежем».",
  ].join("\n");
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // Проверка живости. Именно здесь, до чтения секретов: иначе
    // мониторинг покажет «недоступно» из-за не заданного секрета,
    // и будет непонятно, что сломано.
    if (request.method === "GET" && url.pathname === "/") {
      const state = {
        ok: true,
        bot: env.TELEGRAM_BOT_TOKEN ? "токен задан" : "нет токена",
        model_key: env.MODEL_API_KEY ? "задан" : "нет ключа модели",
        secret: env.WEBHOOK_SECRET ? "задан" : "нет секрета вебхука",
      };
      return new Response(JSON.stringify(state, null, 2),
        { headers: { "Content-Type": "application/json" } });
    }

    if (url.pathname !== "/webhook") {
      return new Response("ok", { status: 200 });
    }

    if (request.method !== "POST") {
      return new Response("ожидаю POST от Telegram", { status: 405 });
    }

    // Секретный токен. Без этой проверки адрес воркера — это
    // публичный способ тратить ваш ключ модели.
    const sent = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (!env.WEBHOOK_SECRET || sent !== env.WEBHOOK_SECRET) {
      // Отвечаем 403 и ничего не пишем в лог: иначе в логе окажется
      // сам секрет из заголовка.
      return new Response("forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("bad json", { status: 400 });
    }

    if (shouldIgnore(update)) {
      return new Response("ok", { status: 200 });
    }

    const message = update.message;
    const chatId = message.chat.id;
    const text = String(message.text).trim();
    const name = message.from?.first_name;

    // Секреты читаем только после проверки: нечего их читать,
    // если запрос поддельный.
    if (!env.TELEGRAM_BOT_TOKEN || !env.MODEL_API_KEY) {
      ctx.waitUntil(log("нет секретов: задайте TELEGRAM_BOT_TOKEN " +
                        "и MODEL_API_KEY через wrangler secret put"));
      return new Response("ok", { status: 200 });
    }

    ctx.waitUntil(answer(env, message, chatId, text, name));
    // Отвечаем сразу: модель думает секунды, Telegram ждать не станет
    // и пришлёт то же обновление ещё раз.
    return new Response("ok", { status: 200 });
  },
};

async function answer(env, message, chatId, text, name) {
  try {
    if (text === "/start" || text === "/help") {
      await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, greet(name));
      return;
    }

    const answer = await askModel(env.MODEL_API_KEY, buildHistory(message));
    await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId, answer);
  } catch (error) {
    await log("сбой: " + (error?.message || String(error)));
    try {
      // Посетителю — короткий текст без подробностей. Подробности
      // ушли в лог воркера, где их видно только владельцу.
      await sendMessage(env.TELEGRAM_BOT_TOKEN, chatId,
                        "Что-то сломалось. Попробуй ещё раз.");
    } catch {
      // Если и это не вышло — молча: вторую попытку отправки
      // посетитель не оценит.
    }
  }
}

async function log(text) {
  // console.log попадает в лог воркера в панели Cloudflare.
  console.log(new Date().toISOString() + " " + text);
}
