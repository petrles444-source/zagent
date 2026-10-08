// Bilingual narrative content for the wedding site.
// The static event config (names, venue, date) lives in wedding-config.ts
// and stays language-neutral; this file holds the creative copy that needs
// human translation: love-story chapters, schedule entries, FAQ, plus a
// few localised labels (venue description, concept).

import type { Lang } from "@/lib/i18n";

type LoveStoryChapter = {
  n: string;
  date: string;
  title: string;
  img: string;
  text: string;
  side: "left" | "right";
};

const loveStoryRu: LoveStoryChapter[] = [
  {
    n: "01",
    date: "Осень 2021",
    title: "Книжный магазин у Большого",
    img: "/wedding/story-bookstore.png",
    text: "Она искала томик Бродского, он — стихи Цветаевой. Их руки встретились на одной полке. Так началась наша история — с тишины и бумажных страниц.",
    side: "left",
  },
  {
    n: "02",
    date: "Зима 2022",
    title: "Полночь на крыше",
    img: "/wedding/story-newyear.png",
    text: "Москва под ногами, бой курантов и бокал горячего глинтвейна. В ту ночь мы впервые пообещали друг другу «навсегда».",
    side: "right",
  },
  {
    n: "03",
    date: "Лето 2024",
    title: "Тоскана под виноградниками",
    img: "/wedding/story-tuscany.png",
    text: "Кипарисы, закат и тишина Кьянти. Под старой оливой прозвучало первое «я люблю тебя», сказанное вслух.",
    side: "left",
  },
  {
    n: "04",
    date: "Весна 2026",
    title: "Тысячa свечей",
    img: "/wedding/story-proposal.png",
    text: "1000 свечей, букет белых пионов и кольцо, спрятанное среди лепестков. Она сказала «да» прежде, чем он успел договорить вопрос.",
    side: "right",
  },
  {
    n: "05",
    date: "22 октября 2026",
    title: "Полночь, которая станет утром",
    img: "/wedding/story-ceremony.png",
    text: "Тот самый день, который начнётся ровно в полночь — там, где тишина становится самой громкой музыкой, а каждый миг обещанием.",
    side: "left",
  },
];

const loveStoryEn: LoveStoryChapter[] = [
  {
    n: "01",
    date: "Autumn 2021",
    title: "The bookshop by the Bolshoi",
    img: "/wedding/story-bookstore.png",
    text: "She was looking for a volume of Brodsky, he — for Tsvetaeva's poems. Their hands met on the same shelf. So our story began — with silence and paper pages.",
    side: "left",
  },
  {
    n: "02",
    date: "Winter 2022",
    title: "Midnight on the roof",
    img: "/wedding/story-newyear.png",
    text: "Moscow beneath our feet, the chimes of midnight, a glass of hot mulled wine. That night, for the first time, we promised each other «forever».",
    side: "right",
  },
  {
    n: "03",
    date: "Summer 2024",
    title: "Tuscany under the vines",
    img: "/wedding/story-tuscany.png",
    text: "Cypresses, sunset, and the quiet of Chianti. Under an old olive tree, the first «I love you» was spoken aloud.",
    side: "left",
  },
  {
    n: "04",
    date: "Spring 2026",
    title: "A thousand candles",
    img: "/wedding/story-proposal.png",
    text: "A thousand candles, a bouquet of white peonies, and a ring hidden among the petals. She said «yes» before he could finish the question.",
    side: "right",
  },
  {
    n: "05",
    date: "October 22, 2026",
    title: "The midnight that becomes morning",
    img: "/wedding/story-ceremony.png",
    text: "The very day that begins exactly at midnight — where silence becomes the loudest music, and every moment a promise.",
    side: "left",
  },
];

type ScheduleItem = { time: string; title: string; desc: string };

const scheduleRu: ScheduleItem[] = [
  { time: "00:00", title: "Встреча гостей", desc: "Бокал игристого и живая музыка в candle-зале" },
  { time: "00:30", title: "Церемония", desc: "Обмен клятвами при свете 300 свечей" },
  { time: "01:15", title: "Фуршет", desc: "Авторские закуски и винная карта" },
  { time: "02:00", title: "Банкет", desc: "Ужин из шести подач от шеф-повара" },
  { time: "03:00", title: "Первый танец", desc: "Под живой струнный квартет" },
  { time: "04:00", title: "Свечи желаний", desc: "Каждый гость зажигает свою свечу" },
  { time: "05:00", title: "Торт & десерты", desc: "Пионы из марципана и шоколадный фонтан" },
  { time: "06:00", title: "Фейерверк", desc: "Золотой салют над парком усадьбы" },
];

const scheduleEn: ScheduleItem[] = [
  { time: "00:00", title: "Welcome", desc: "A glass of sparkling and live music in the candle hall" },
  { time: "00:30", title: "Ceremony", desc: "Vows exchanged by the light of 300 candles" },
  { time: "01:15", title: "Reception", desc: "Signature canapés and the wine list" },
  { time: "02:00", title: "Banquet", desc: "A six-course dinner by the chef" },
  { time: "03:00", title: "First dance", desc: "To a live string quartet" },
  { time: "04:00", title: "Candles of wishes", desc: "Each guest lights their own candle" },
  { time: "05:00", title: "Cake & desserts", desc: "Marzipan peonies and a chocolate fountain" },
  { time: "06:00", title: "Fireworks", desc: "A golden salute above the estate park" },
];

type FaqItem = { q: string; a: string };

const faqRu: FaqItem[] = [
  {
    q: "Можно ли приехать с детьми?",
    a: "Мы очень любим детей, но этот вечер мы хотим посвятить только взрослым гостям. Организаторы помогут с рекомендациями няни на вечер — напишите нам заранее.",
  },
  {
    q: "Будет ли парковка?",
    a: "Да, на территории усадьбы работает бесплатный паркинг с ваlet-сервисом. Для гостей из центра Москвы будет организован трансфер от станции метро «Барвиха» в 23:15.",
  },
  {
    q: "Что подарить?",
    a: "Лучший подарок — ваше присутствие. Если же хочется порадовать нас, мы будем благодарны за вклад в наше свадебное путешествие или букет белых пионов.",
  },
  {
    q: "Нужно ли подтверждать участие?",
    a: "Да, пожалуйста, заполните форму RSVP до 1 октября 2026 года. Это поможет нам учесть предпочтения по меню и напиткам.",
  },
  {
    q: "Будет ли фотосъёмка?",
    a: "Мы наняли команду из двух фотографов и видеографа. Профессиональные снимки мы пришлём после свадьбы, а своими фото просим делиться по хэштегу #СофияАлександрПолночь.",
  },
];

const faqEn: FaqItem[] = [
  {
    q: "Can we bring children?",
    a: "We love children dearly, but this evening we'd like to dedicate to our adult guests. Our organisers can help with babysitter recommendations for the night — please write to us in advance.",
  },
  {
    q: "Will there be parking?",
    a: "Yes, the estate has free parking with a valet service. For guests from central Moscow, a shuttle will run from the Barvikha metro station at 23:15.",
  },
  {
    q: "What should we gift?",
    a: "The best gift is your presence. If you'd like to delight us, we'd be grateful for a contribution to our honeymoon or a bouquet of white peonies.",
  },
  {
    q: "Do we need to RSVP?",
    a: "Yes, please fill the RSVP form by October 1, 2026. It helps us plan the menu and drinks.",
  },
  {
    q: "Will there be a photographer?",
    a: "We've hired a team of two photographers and a videographer. We'll send the professional shots after the wedding, and we invite you to share your own photos with the hashtag #SofiaAlexanderMidnight.",
  },
];

// A handful of long-form localised strings used across sections.
const miscRu = {
  concept:
    "Свечи, пионы и полуночный шёпот. Мы празднуем начало нового дня ровно в полночь — там, где тишина становится самой громкой музыкой, а каждый миг — обещанием.",
  venueDescription:
    "Историческая подмосковная усадьба XIX века, утопающая в старинном парке. Главный зал освещается тремя сотнями свечей, а терраса выходит на зеркальный пруд, где ровно в шесть утра запускают золотой салют.",
  venuePerks: [
    "Парковка и valet для гостей",
    "Трансфер от м. «Барвиха» в 23:15",
    "Номера для гостей при усадьбе",
  ],
  coupleQuotes: {
    bride: "«Я всегда знала, что любовь пахнет пионами и свечами.»",
    groom: "«Она вошла в комнату — и время остановилось ровно на полночь.»",
  },
  closingQuote:
    "«Любовь — это когда полуночь кажется началом, а не концом дня. Спасибо, что будете с нами в ту ночь, которая начнёт нашу вечность.»",
};

const miscEn = {
  concept:
    "Candles, peonies, and a midnight whisper. We celebrate the beginning of a new day exactly at midnight — where silence becomes the loudest music, and every moment a promise.",
  venueDescription:
    "A historic 19th-century Muscovite estate, nestled in an old park. The main hall is lit by three hundred candles, and the terrace overlooks a mirror pond where, at exactly six in the morning, a golden fireworks salute is launched.",
  venuePerks: [
    "Parking and valet for guests",
    "Shuttle from Barvikha metro at 23:15",
    "Guest rooms on the estate grounds",
  ],
  coupleQuotes: {
    bride: "«I always knew that love smells of peonies and candles.»",
    groom: "«She walked into the room — and time stopped at exactly midnight.»",
  },
  closingQuote:
    "«Love is when midnight feels like a beginning, not an end. Thank you for being with us on the night that starts our forever.»",
};

export const contentByLang = {
  ru: {
    loveStory: loveStoryRu,
    schedule: scheduleRu,
    faq: faqRu,
    ...miscRu,
  },
  en: {
    loveStory: loveStoryEn,
    schedule: scheduleEn,
    faq: faqEn,
    ...miscEn,
  },
} as const;

export type WeddingContent = (typeof contentByLang)[Lang];
