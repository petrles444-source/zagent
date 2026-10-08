// Lightweight i18n dictionary for the wedding site's UI chrome.
// Section-specific narrative content (love-story chapters, schedule
// descriptions, FAQ answers) stays in Russian in wedding-config.ts —
// those are creative copy that would need human translation. The
// toggle covers all UI labels, nav, buttons, form fields, and
// section headings so international guests can navigate the site.

export type Lang = "ru" | "en";

export const LANGS: { code: Lang; label: string; short: string }[] = [
  { code: "ru", label: "Русский", short: "RU" },
  { code: "en", label: "English", short: "EN" },
];

export type TranslationKey =
  | "nav.home"
  | "nav.countdown"
  | "nav.loveStory"
  | "nav.about"
  | "nav.party"
  | "nav.details"
  | "nav.travel"
  | "nav.schedule"
  | "nav.tables"
  | "nav.gallery"
  | "nav.photos"
  | "nav.rsvp"
  | "nav.guestbook"
  | "nav.locks"
  | "nav.faq"
  | "common.saveTheDate"
  | "common.at"
  | "common.weekday.thursday"
  | "hero.confirmVisit"
  | "hero.countdown"
  | "hero.scrollDown"
  | "hero.withLove"
  | "countdown.eyebrow"
  | "countdown.title"
  | "countdown.subtitle"
  | "countdown.days"
  | "countdown.hours"
  | "countdown.minutes"
  | "countdown.seconds"
  | "countdown.today"
  | "countdown.thankYou"
  | "countdown.firstDance"
  | "countdown.danceNow"
  | "story.eyebrow"
  | "story.title"
  | "story.subtitle"
  | "story.couple"
  | "story.coupleTitle"
  | "story.bride"
  | "story.groom"
  | "party.eyebrow"
  | "party.title"
  | "party.subtitle"
  | "details.eyebrow"
  | "details.title"
  | "details.subtitle"
  | "details.date"
  | "details.venue"
  | "details.dressCode"
  | "details.estate"
  | "details.openMap"
  | "details.buildRoute"
  | "details.addToCalendar"
  | "details.share"
  | "details.shareCard"
  | "details.copied"
  | "details.calendarAdded"
  | "palette.eyebrow"
  | "palette.title"
  | "palette.blackTie"
  | "lookbook.eyebrow"
  | "travel.eyebrow"
  | "travel.title"
  | "travel.subtitle"
  | "schedule.eyebrow"
  | "schedule.title"
  | "schedule.subtitle"
  | "schedule.untilMidnight"
  | "schedule.oneMoment"
  | "tables.eyebrow"
  | "tables.title"
  | "tables.subtitle"
  | "tables.search"
  | "tables.find"
  | "tables.searching"
  | "tables.example"
  | "tables.allTables"
  | "tables.guests"
  | "tables.yourTable"
  | "tables.seatMates"
  | "tables.notFound"
  | "tables.notFoundDesc"
  | "gallery.eyebrow"
  | "gallery.title"
  | "gallery.subtitle"
  | "gallery.enlarge"
  | "gallery.close"
  | "gallery.prev"
  | "gallery.next"
  | "photos.eyebrow"
  | "photos.title"
  | "photos.subtitle"
  | "photos.yourName"
  | "photos.caption"
  | "photos.photo"
  | "photos.dropOrClick"
  | "photos.submit"
  | "photos.submitting"
  | "photos.moderationNote"
  | "photos.empty"
  | "photos.emptyDesc"
  | "photos.open"
  | "photos.shots"
  | "rsvp.eyebrow"
  | "rsvp.title"
  | "rsvp.subtitle"
  | "rsvp.name"
  | "rsvp.phone"
  | "rsvp.email"
  | "rsvp.guests"
  | "rsvp.attending"
  | "rsvp.yes"
  | "rsvp.maybe"
  | "rsvp.no"
  | "rsvp.meal"
  | "rsvp.drink"
  | "rsvp.message"
  | "rsvp.submit"
  | "rsvp.submitting"
  | "rsvp.deadline"
  | "rsvp.confirmed"
  | "rsvp.totalGuests"
  | "rsvp.undecided"
  | "rsvp.responses"
  | "rsvp.thanks"
  | "rsvp.thanksDesc"
  | "rsvp.another"
  | "poll.title"
  | "poll.subtitle"
  | "poll.yes"
  | "poll.maybe"
  | "poll.no"
  | "poll.totalVotes"
  | "poll.last14"
  | "poll.thanks"
  | "poll.updated"
  | "guestbook.eyebrow"
  | "guestbook.title"
  | "guestbook.subtitle"
  | "guestbook.yourName"
  | "guestbook.wish"
  | "guestbook.attending"
  | "guestbook.yes"
  | "guestbook.maybe"
  | "guestbook.no"
  | "guestbook.submit"
  | "guestbook.submitting"
  | "guestbook.empty"
  | "guestbook.likes"
  | "guestbook.liked"
  | "guestbook.like"
  | "guestbook.like2"
  | "guestbook.unlike"
  | "guestbook.search"
  | "guestbook.searchPlaceholder"
  | "guestbook.wishes"
  | "guestbook.updatedNow"
  | "songs.eyebrow"
  | "songs.title"
  | "songs.subtitle"
  | "songs.yourName"
  | "songs.song"
  | "songs.artist"
  | "songs.submit"
  | "songs.submitting"
  | "songs.playlist"
  | "songs.empty"
  | "locks.eyebrow"
  | "locks.title"
  | "locks.subtitle"
  | "locks.initials"
  | "locks.message"
  | "locks.color"
  | "locks.hang"
  | "locks.hanging"
  | "locks.locksOnBridge"
  | "locks.preview"
  | "locks.yourLock"
  | "faq.eyebrow"
  | "faq.title"
  | "faq.subtitle"
  | "faq.questions"
  | "faq.question"
  | "faq.stillQuestions"
  | "closing.withLove"
  | "closing.quote"
  | "closing.confirmVisit"
  | "closing.keepAsKeepsake"
  | "footer.madeWithLove"
  | "admin.login.title"
  | "admin.login.subtitle"
  | "admin.login.password"
  | "admin.login.submit"
  | "admin.login.checking"
  | "admin.login.back"
  | "admin.cabinet"
  | "admin.logout"
  | "admin.backToSite"
  | "admin.confirmed"
  | "admin.totalGuests"
  | "admin.wishes"
  | "admin.songs"
  | "admin.meal"
  | "admin.drinks"
  | "admin.export"
  | "admin.refresh"
  | "admin.updated"
  | "admin.empty"
  | "admin.noErrors";

type Dict = Record<TranslationKey, string>;

const ru: Dict = {
  "nav.home": "Главная",
  "nav.countdown": "Отсчёт",
  "nav.loveStory": "История любви",
  "nav.about": "О нас",
  "nav.party": "Свита",
  "nav.details": "Детали",
  "nav.travel": "Логистика",
  "nav.schedule": "Программа",
  "nav.tables": "Мой стол",
  "nav.gallery": "Галерея",
  "nav.photos": "Фото",
  "nav.rsvp": "RSVP",
  "nav.guestbook": "Пожелания",
  "nav.locks": "Замки",
  "nav.faq": "FAQ",
  "common.saveTheDate": "Save the Date",
  "common.at": "в",
  "common.weekday.thursday": "четверг",
  "hero.confirmVisit": "Подтвердить визит",
  "hero.countdown": "Обратный отсчёт",
  "hero.scrollDown": "Листайте",
  "hero.withLove": "с любовью",
  "countdown.eyebrow": "До торжества осталось",
  "countdown.title": "Обратный отсчёт",
  "countdown.subtitle": "Каждая секунда приближает нас к полуночи, когда начнётся наш новый день.",
  "countdown.days": "Дней",
  "countdown.hours": "Часов",
  "countdown.minutes": "Минут",
  "countdown.seconds": "Секунд",
  "countdown.today": "Сегодня наш день",
  "countdown.thankYou": "Спасибо всем, кто разделил с нами эту ночь.",
  "countdown.firstDance": "Первый танец",
  "countdown.danceNow": "уже звучит",
  "story.eyebrow": "Наша история любви",
  "story.title": "Пять глав",
  "story.subtitle": "От книжной полки до полуночи — каждая глава вела нас сюда. Листайте вниз, чтобы пройти их вместе с нами.",
  "story.couple": "Наша история",
  "story.coupleTitle": "Двое. Одна ночь. Навсегда.",
  "story.bride": "Невеста",
  "story.groom": "Жених",
  "party.eyebrow": "Наша свита",
  "party.title": "Свидетели и друзья",
  "party.subtitle": "Те, без кого эта ночь не состоялась бы. Они будут рядом от первой до последней свечи.",
  "details.eyebrow": "Детали торжества",
  "details.title": "Где и когда",
  "details.subtitle": "Всё, что нужно знать, чтобы провести с нами эту ночь.",
  "details.date": "Дата",
  "details.venue": "Место",
  "details.dressCode": "Дресс-код",
  "details.estate": "Усадьба",
  "details.openMap": "Открыть карту",
  "details.buildRoute": "Построить маршрут",
  "details.addToCalendar": "В календарь",
  "details.share": "Поделиться",
  "details.shareCard": "Карточка отсчёта",
  "details.copied": "Скопировано!",
  "details.calendarAdded": "Добавлено в календарь",
  "palette.eyebrow": "Дресс-код",
  "palette.title": "Палитра вечера",
  "palette.blackTie": "Black Tie · вечерний",
  "lookbook.eyebrow": "Вдохновение вечера",
  "travel.eyebrow": "Логистика и ночлег",
  "travel.title": "Где переночевать",
  "travel.subtitle": "Чтобы ночь была по-настоящему вашей — выберите отель рядом с усадьбой или воспользуйтесь трансфером.",
  "schedule.eyebrow": "Программа вечера",
  "schedule.title": "Ночь в деталях",
  "schedule.subtitle": "От первой свечи до золотого салюта — каждая минута нашего дня расписана с любовью.",
  "schedule.untilMidnight": "до полуночи",
  "schedule.oneMoment": "осталось одно мгновение",
  "tables.eyebrow": "Где вас ждут",
  "tables.title": "Найдите свой стол",
  "tables.subtitle": "Введите вашу фамилию — и мы покажем, за каким цветочным столом вы сидите и с кем разделите этот вечер.",
  "tables.search": "Поиск стола по фамилии",
  "tables.find": "Найти стол",
  "tables.searching": "Ищем…",
  "tables.example": "Например:",
  "tables.allTables": "Все столы вечера",
  "tables.guests": "гость|гостя|гостей",
  "tables.yourTable": "Ваш стол",
  "tables.seatMates": "Рядом с вами сидят",
  "tables.notFound": "Вас пока нет в списке",
  "tables.notFoundDesc": "Не переживайте — организаторы при входе помогут найти ваш стол. Возможно, фамилия записана иначе.",
  "gallery.eyebrow": "Мгновения",
  "gallery.title": "Галерея",
  "gallery.subtitle": "Нажмите на любой кадр, чтобы увидеть его целиком. Листайте стрелками ← → или Esc для выхода.",
  "gallery.enlarge": "увеличить",
  "gallery.close": "Закрыть",
  "gallery.prev": "Предыдущее",
  "gallery.next": "Следующее",
  "photos.eyebrow": "Живые мгновения",
  "photos.title": "Стена фото",
  "photos.subtitle": "Делитесь снимками с вечера — мы добавим их на эту стену после проверки. Пусть ночь останется с нами навсегда.",
  "photos.yourName": "Ваше имя",
  "photos.caption": "Подпись (необязательно)",
  "photos.photo": "Фотография",
  "photos.dropOrClick": "Перетащите или нажмите для выбора",
  "photos.submit": "Отправить фото",
  "photos.submitting": "Отправляем…",
  "photos.moderationNote": "Фото появится после проверки организатором",
  "photos.empty": "Стена пока пуста",
  "photos.emptyDesc": "Будьте первым, кто поделится снимком",
  "photos.open": "открыть",
  "photos.shots": "снимок|снимка|снимков",
  "rsvp.eyebrow": "Подтверждение визита",
  "rsvp.title": "Будете ли вы с нами",
  "rsvp.subtitle": "Пожалуйста, заполните форму до 1 октября 2026 года. Это поможет нам учесть предпочтения по меню и напиткам.",
  "rsvp.name": "Ваше имя",
  "rsvp.phone": "Телефон",
  "rsvp.email": "E-mail",
  "rsvp.guests": "Количество гостей",
  "rsvp.attending": "Сможете прийти?",
  "rsvp.yes": "Да, буду",
  "rsvp.maybe": "Пока не уверен",
  "rsvp.no": "К сожалению, нет",
  "rsvp.meal": "Предпочтения по меню",
  "rsvp.drink": "Напиток вечера",
  "rsvp.message": "Сообщение молодожёнам",
  "rsvp.submit": "Отправить ответ",
  "rsvp.submitting": "Отправляем…",
  "rsvp.deadline": "До дедлайна RSVP — 1 октября 2026",
  "rsvp.confirmed": "Подтвердили",
  "rsvp.totalGuests": "Всего гостей",
  "rsvp.undecided": "Сомневаются",
  "rsvp.responses": "Ответов",
  "rsvp.thanks": "Благодарим вас",
  "rsvp.thanksDesc": "Ваш ответ получен. Мы напишем вам накануне торжества, чтобы подтвердить все детали. До встречи под звёздами!",
  "rsvp.another": "Отправить ещё ответ",
  "poll.title": "А вы придёте?",
  "poll.subtitle": "Быстрый опрос — покажите, что будете с нами в полночь.",
  "poll.yes": "Буду",
  "poll.maybe": "Возможно",
  "poll.no": "Не смогу",
  "poll.totalVotes": "Всего голосов",
  "poll.last14": "за 14 дней",
  "poll.thanks": "Спасибо за голос!",
  "poll.updated": "Голос обновлён",
  "guestbook.eyebrow": "Стена пожеланий",
  "guestbook.title": "Тёплые слова",
  "guestbook.subtitle": "Оставьте пожелание — мы перечитаем их все после полуночи, когда стихнет музыка.",
  "guestbook.yourName": "Ваше имя",
  "guestbook.wish": "Пожелание",
  "guestbook.attending": "Сможете прийти?",
  "guestbook.yes": "Буду",
  "guestbook.maybe": "Возможно",
  "guestbook.no": "Не смогу",
  "guestbook.submit": "Оставить пожелание",
  "guestbook.submitting": "Отправляем…",
  "guestbook.empty": "Пока пусто",
  "guestbook.likes": "лайк|лайка|лайков",
  "guestbook.liked": "вам понравилось",
  "guestbook.like": "нравится",
  "guestbook.unlike": "Убрать лайк",
  "guestbook.like2": "Поставить лайк",
  "guestbook.search": "Поиск",
  "guestbook.searchPlaceholder": "Искать по имени или тексту…",
  "guestbook.wishes": "пожелание|пожелания|пожеланий",
  "guestbook.updatedNow": "обновлено только что",
  "songs.eyebrow": "Танцпол",
  "songs.title": "Закажите песню",
  "songs.subtitle": "Что должно звучать в полночь? Предложите трек — и, возможно, именно под него мы станцуем наш первый танец.",
  "songs.yourName": "Ваше имя",
  "songs.song": "Песня",
  "songs.artist": "Исполнитель",
  "songs.submit": "Заказать",
  "songs.submitting": "Добавляем…",
  "songs.playlist": "Плейлист вечера",
  "songs.empty": "Пока никто не предложил трек. Будьте первым!",
  "locks.eyebrow": "Мост любви",
  "locks.title": "Замки навсегда",
  "locks.subtitle": "Повесьте свой замок на наш виртуальный мост — символ того, что ваша любовь, как и наша, теперь заперта навечно. Бросьте ключ в реку времени.",
  "locks.initials": "Ваши инициалы",
  "locks.message": "Послание (необязательно)",
  "locks.color": "Цвет замка",
  "locks.hang": "Повесить замок",
  "locks.hanging": "Вешаем…",
  "locks.locksOnBridge": "замок|замка|замков",
  "locks.preview": "предпросмотр вашего замка",
  "locks.yourLock": "ваш замок",
  "faq.eyebrow": "Частые вопросы",
  "faq.title": "Полезно знать",
  "faq.subtitle": "Собрали ответы на вопросы, которые чаще всего задают наши гости.",
  "faq.stillQuestions": "Остались вопросы? Напишите нам:",
  "faq.questions": "вопрос|вопроса|вопросов",
  "closing.withLove": "с любовью и нетерпением",
  "closing.quote": "«Любовь — это когда полуночь кажется началом, а не концом дня. Спасибо, что будете с нами в ту ночь, которая начнёт нашу вечность.»",
  "closing.confirmVisit": "Подтвердить визит",
  "closing.keepAsKeepsake": "Сохранить на память",
  "footer.madeWithLove": "Сделано с любовью и множеством свечей",
  "admin.login.title": "Кабинет организатора",
  "admin.login.subtitle": "Введите пароль для доступа к ответам RSVP, пожеланиям и плейлисту.",
  "admin.login.password": "Пароль администратора",
  "admin.login.submit": "Войти",
  "admin.login.checking": "Проверяем…",
  "admin.login.back": "← Вернуться на сайт",
  "admin.cabinet": "Кабинет",
  "admin.logout": "Выйти",
  "admin.backToSite": "← Сайт",
  "admin.confirmed": "Подтвердили",
  "admin.totalGuests": "Всего гостей",
  "admin.wishes": "Пожеланий",
  "admin.songs": "Песен",
  "admin.meal": "Меню",
  "admin.drinks": "Напитки",
  "admin.export": "↓ Экспорт CSV",
  "admin.refresh": "↻ Обновить",
  "admin.updated": "обновлено",
  "admin.empty": "Пока ничего нет",
  "admin.noErrors": "Ошибок нет",
};

const en: Dict = {
  "nav.home": "Home",
  "nav.countdown": "Countdown",
  "nav.loveStory": "Love story",
  "nav.about": "About us",
  "nav.party": "Wedding party",
  "nav.details": "Details",
  "nav.travel": "Travel",
  "nav.schedule": "Schedule",
  "nav.tables": "My table",
  "nav.gallery": "Gallery",
  "nav.photos": "Photos",
  "nav.rsvp": "RSVP",
  "nav.guestbook": "Wishes",
  "nav.locks": "Locks",
  "nav.faq": "FAQ",
  "common.saveTheDate": "Save the Date",
  "common.at": "at",
  "common.weekday.thursday": "Thursday",
  "hero.confirmVisit": "Confirm attendance",
  "hero.countdown": "Countdown",
  "hero.scrollDown": "Scroll",
  "hero.withLove": "with love",
  "countdown.eyebrow": "Time until the celebration",
  "countdown.title": "Countdown",
  "countdown.subtitle": "Every second brings us closer to midnight, when our new day begins.",
  "countdown.days": "Days",
  "countdown.hours": "Hours",
  "countdown.minutes": "Minutes",
  "countdown.seconds": "Seconds",
  "countdown.today": "Today is our day",
  "countdown.thankYou": "Thank you to everyone who shared this night with us.",
  "countdown.firstDance": "First dance",
  "countdown.danceNow": "is playing now",
  "story.eyebrow": "Our love story",
  "story.title": "Five chapters",
  "story.subtitle": "From a bookshelf to midnight — every chapter led us here. Scroll down to walk through them with us.",
  "story.couple": "Our story",
  "story.coupleTitle": "Two. One night. Forever.",
  "story.bride": "Bride",
  "story.groom": "Groom",
  "party.eyebrow": "Our party",
  "party.title": "Witnesses & friends",
  "party.subtitle": "Those without whom this night wouldn't happen. They'll be by our side from the first to the last candle.",
  "details.eyebrow": "Celebration details",
  "details.title": "Where & when",
  "details.subtitle": "Everything you need to know to spend this night with us.",
  "details.date": "Date",
  "details.venue": "Venue",
  "details.dressCode": "Dress code",
  "details.estate": "Estate",
  "details.openMap": "Open map",
  "details.buildRoute": "Get directions",
  "details.addToCalendar": "Add to calendar",
  "details.share": "Share",
  "details.shareCard": "Countdown card",
  "details.copied": "Copied!",
  "details.calendarAdded": "Added to calendar",
  "palette.eyebrow": "Dress code",
  "palette.title": "Evening palette",
  "palette.blackTie": "Black Tie · evening",
  "lookbook.eyebrow": "Evening inspiration",
  "travel.eyebrow": "Logistics & lodging",
  "travel.title": "Where to stay",
  "travel.subtitle": "To make the night truly yours — choose a hotel near the estate or use our shuttle.",
  "schedule.eyebrow": "Evening programme",
  "schedule.title": "The night in detail",
  "schedule.subtitle": "From the first candle to the golden fireworks — every minute of our day is planned with love.",
  "schedule.untilMidnight": "until midnight",
  "schedule.oneMoment": "one moment left",
  "tables.eyebrow": "Where you're expected",
  "tables.title": "Find your table",
  "tables.subtitle": "Enter your surname — we'll show you which flower-named table you're at and who you'll share the evening with.",
  "tables.search": "Search table by surname",
  "tables.find": "Find table",
  "tables.searching": "Searching…",
  "tables.example": "e.g.:",
  "tables.allTables": "All tables of the evening",
  "tables.guests": "guest|guests|guests",
  "tables.yourTable": "Your table",
  "tables.seatMates": "Seated with you",
  "tables.notFound": "You're not on the list yet",
  "tables.notFoundDesc": "Don't worry — our organisers will help you find your table at the entrance. Your surname may be spelled differently.",
  "gallery.eyebrow": "Moments",
  "gallery.title": "Gallery",
  "gallery.subtitle": "Click any photo to view it in full. Use ← → arrows or Esc to close.",
  "gallery.enlarge": "enlarge",
  "gallery.close": "Close",
  "gallery.prev": "Previous",
  "gallery.next": "Next",
  "photos.eyebrow": "Live moments",
  "photos.title": "Photo wall",
  "photos.subtitle": "Share photos from the evening — we'll add them to this wall after review. Let the night stay with us forever.",
  "photos.yourName": "Your name",
  "photos.caption": "Caption (optional)",
  "photos.photo": "Photo",
  "photos.dropOrClick": "Drop or click to choose",
  "photos.submit": "Submit photo",
  "photos.submitting": "Uploading…",
  "photos.moderationNote": "Photo appears after organiser review",
  "photos.empty": "The wall is empty",
  "photos.emptyDesc": "Be the first to share a photo",
  "photos.open": "open",
  "photos.shots": "photo|photos|photos",
  "rsvp.eyebrow": "Attendance confirmation",
  "rsvp.title": "Will you join us",
  "rsvp.subtitle": "Please fill the form by October 1, 2026. It helps us plan the menu and drinks.",
  "rsvp.name": "Your name",
  "rsvp.phone": "Phone",
  "rsvp.email": "Email",
  "rsvp.guests": "Number of guests",
  "rsvp.attending": "Can you attend?",
  "rsvp.yes": "Yes, I'll be there",
  "rsvp.maybe": "Not sure yet",
  "rsvp.no": "Unfortunately, no",
  "rsvp.meal": "Meal preference",
  "rsvp.drink": "Evening drink",
  "rsvp.message": "Message to the couple",
  "rsvp.submit": "Send response",
  "rsvp.submitting": "Sending…",
  "rsvp.deadline": "RSVP deadline — October 1, 2026",
  "rsvp.confirmed": "Confirmed",
  "rsvp.totalGuests": "Total guests",
  "rsvp.undecided": "Undecided",
  "rsvp.responses": "Responses",
  "rsvp.thanks": "Thank you",
  "rsvp.thanksDesc": "Your response is received. We'll write to you the day before to confirm all details. See you under the stars!",
  "rsvp.another": "Submit another response",
  "poll.title": "Will you make it?",
  "poll.subtitle": "Quick poll — let us know you'll be with us at midnight.",
  "poll.yes": "Yes",
  "poll.maybe": "Maybe",
  "poll.no": "No",
  "poll.totalVotes": "Total votes",
  "poll.last14": "last 14 days",
  "poll.thanks": "Thanks for voting!",
  "poll.updated": "Vote updated",
  "guestbook.eyebrow": "Wishes wall",
  "guestbook.title": "Warm words",
  "guestbook.subtitle": "Leave a wish — we'll reread them all after midnight, when the music fades.",
  "guestbook.yourName": "Your name",
  "guestbook.wish": "Your wish",
  "guestbook.attending": "Can you attend?",
  "guestbook.yes": "Yes",
  "guestbook.maybe": "Maybe",
  "guestbook.no": "No",
  "guestbook.submit": "Leave a wish",
  "guestbook.submitting": "Sending…",
  "guestbook.empty": "Nothing here yet",
  "guestbook.likes": "like|likes|likes",
  "guestbook.liked": "you liked this",
  "guestbook.like": "like",
  "guestbook.unlike": "Unlike",
  "guestbook.like2": "Like",
  "guestbook.search": "Search",
  "guestbook.searchPlaceholder": "Search by name or text…",
  "guestbook.wishes": "wish|wishes|wishes",
  "guestbook.updatedNow": "updated just now",
  "songs.eyebrow": "Dance floor",
  "songs.title": "Request a song",
  "songs.subtitle": "What should play at midnight? Suggest a track — and maybe we'll dance our first dance to it.",
  "songs.yourName": "Your name",
  "songs.song": "Song",
  "songs.artist": "Artist",
  "songs.submit": "Request",
  "songs.submitting": "Adding…",
  "songs.playlist": "Evening playlist",
  "songs.empty": "No tracks yet. Be the first!",
  "locks.eyebrow": "Bridge of love",
  "locks.title": "Locks forever",
  "locks.subtitle": "Hang your lock on our virtual bridge — a symbol that your love, like ours, is now locked forever. Throw the key into the river of time.",
  "locks.initials": "Your initials",
  "locks.message": "Message (optional)",
  "locks.color": "Lock colour",
  "locks.hang": "Hang a lock",
  "locks.hanging": "Hanging…",
  "locks.locksOnBridge": "lock|locks|locks",
  "locks.preview": "preview of your lock",
  "locks.yourLock": "your lock",
  "faq.eyebrow": "Frequently asked",
  "faq.title": "Good to know",
  "faq.subtitle": "Answers to the questions our guests ask most.",
  "faq.stillQuestions": "Still have questions? Write to us:",
  "faq.questions": "question|questions|questions",
  "closing.withLove": "with love and anticipation",
  "closing.quote": "\"Love is when midnight feels like a beginning, not an end. Thank you for being with us on the night that starts our forever.\"",
  "closing.confirmVisit": "Confirm attendance",
  "closing.keepAsKeepsake": "Save as keepsake",
  "footer.madeWithLove": "Made with love and a multitude of candles",
  "admin.login.title": "Organiser cabinet",
  "admin.login.subtitle": "Enter the password to access RSVP responses, wishes, and the playlist.",
  "admin.login.password": "Admin password",
  "admin.login.submit": "Sign in",
  "admin.login.checking": "Checking…",
  "admin.login.back": "← Back to site",
  "admin.cabinet": "Cabinet",
  "admin.logout": "Sign out",
  "admin.backToSite": "← Site",
  "admin.confirmed": "Confirmed",
  "admin.totalGuests": "Total guests",
  "admin.wishes": "Wishes",
  "admin.songs": "Songs",
  "admin.meal": "Meal",
  "admin.drinks": "Drinks",
  "admin.export": "↓ Export CSV",
  "admin.refresh": "↻ Refresh",
  "admin.updated": "updated",
  "admin.empty": "Nothing yet",
  "admin.noErrors": "No errors",
};

export const translations: Record<Lang, Dict> = { ru, en };

/** Russian plural-form helper that also works for the English "guests" key. */
export function pluralize(
  lang: Lang,
  n: number,
  forms: [string, string, string]
): string {
  if (lang === "en") {
    return n === 1 ? forms[0] : forms[1];
  }
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return forms[0];
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return forms[1];
  return forms[2];
}
