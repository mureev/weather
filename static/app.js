/* CM Weather -- the front end.
 *
 * Design constraint that shapes everything below: **an iOS PWA cannot refresh
 * in the background. At all.** Background Sync, Periodic Background Sync and
 * Background Fetch are all unsupported, and silent push is prohibited by
 * design -- a service worker that takes a push without showing a notification
 * has its subscription revoked after three strikes.
 *
 * That is not a limitation you engineer around. It is one you design *for*.
 * So: render the cached payload instantly, fetch in the background, re-render
 * when it lands, and put the timestamp somewhere you cannot miss it. The app
 * never pretends the number on screen is newer than it is.
 */
'use strict';

const BASE = (window.YW_BASE || '') + '/';
const PRECISION = window.YW_PRECISION || 2;
const $ = (id) => document.getElementById(id);

const LS = { place: 'yw.place', payload: 'yw.payload', source: 'yw.source',
             lang: 'yw.lang' };

/* ---- language: Russian or English, chosen on the device ---------------------
 * The footer's switch, else the browser's first preference that is one of the
 * two, else English; `?lang=` sets it from a link. Nothing about the choice
 * goes upstream (invariant 5), so the sources' Russian reaches an English
 * screen as what it *means*, never as a translation. DECISIONS.md §36.
 */
const LANG = (() => {
  try {
    const q = new URLSearchParams(location.search).get('lang');
    if (q === 'ru' || q === 'en') localStorage.setItem(LS.lang, q);
    const v = q || localStorage.getItem(LS.lang);
    if (v === 'ru' || v === 'en') return v;
  } catch (e) { /* private mode: detection still works */ }
  for (const l of navigator.languages || [navigator.language]) {
    const p = String(l || '').slice(0, 2).toLowerCase();
    if (p === 'ru' || p === 'en') return p;
  }
  return 'en';
})();
const EN = LANG === 'en' ? 1 : 0;

// Every string the interface says, both languages side by side; a test reads
// it back from the running page.
const STR = {
  app: ['Погода', 'Weather'],
  loading: ['Загружаем погоду…', 'Loading the weather…'],
  refresh: ['Обновить', 'Refresh'],
  close: ['Закрыть', 'Close'],
  gps: ['по геолокации', 'by location'],
  otherLang: ['English', 'Русский'],
  today: ['Сегодня', 'Today'],
  tomorrow: ['Завтра', 'Tomorrow'],
  // Capitalised: it stands where a time does, as a column's name, and in
  // lower case beside «08:00» it read as a word that had lost its sentence.
  now: ['Сейчас', 'Now'],
  updatedAt: ['обновлено в %1', 'updated at %1'],
  minAgo: ['%1 мин назад · %2', '%1 min ago · %2'],
  hAgo: ['%1 ч назад · %2', '%1 h ago · %2'],
  noData: ['нет данных', 'no data'],
  hourly: ['По часам', 'Hourly'],
  details: ['Подробности', 'Details'],
  parts: ['По времени суток', 'Through the day'],
  feelsLike: ['ощущается как %1', 'feels like %1'],
  feels: ['ощущается %1', 'feels %1'],
  gustsTo: ['порывы до %1', 'gusts to %1'],
  noWeather: ['Погоду сейчас получить не удалось.', 'The weather could not be fetched just now.'],
  degraded: ['неполные данные', 'incomplete data'],
  stale: ['устарело', 'out of date'],
  down: ['нет данных', 'no data'],
  whatsWrong: ['Что не так', 'What is wrong'],
  geoNone: ['Геолокация недоступна в этом браузере.', 'Location is not available in this browser.'],
  geoDenied: ['Доступ к геолокации запрещён. Разрешите его в настройках Safari.',
              'Location access is off. Allow it in Safari’s settings.'],
  geoFail: ['Не удалось определить местоположение.', 'Could not determine your location.'],
  place: ['Место', 'Place'],
  search: ['Найти город…', 'Find a city…'],
  myLoc: ['Моё местоположение', 'My location'],
  on: ['включено', 'on'],
  found: ['Найдено', 'Results'],
  nothing: ['Ничего не найдено', 'Nothing found'],
  cities: ['Города', 'Cities'],
  wind: ['Ветер', 'Wind'],
  humidity: ['Влажность', 'Humidity'],
  pressure: ['Давление', 'Pressure'],
  sunrise: ['Восход', 'Sunrise'],
  sunset: ['Закат', 'Sunset'],
  uv: ['УФ-индекс', 'UV index'],
  water: ['Вода', 'Water'],
  feelsRange: ['Ощущается как', 'Feels like'],
  avg: ['Средняя за сутки', 'Daily mean'],
  gusts: ['Порывы', 'Gusts'],
  precip: ['Осадки', 'Precipitation'],
  precipProb: ['Вероятность осадков', 'Chance of precipitation'],
  snow: ['Снег', 'Snow'],
  snowDepth: ['Высота снега', 'Snow depth'],
  kp: ['Геомагнитная активность', 'Geomagnetic activity'],
  daylight: ['Долгота дня', 'Daylight'],
  magnetic: ['Магнитное поле', 'Magnetic field'],
  ms: ['м/с', 'm/s'],
  mm: ['мм', 'mm'],
  mmHg: ['мм', 'mmHg'],
  cm: ['см', 'cm'],
  dayNoData: ['У источника «%1» нет данных на этот день.<br>Попробуйте другой источник выше.',
              '%1 has nothing for this day.<br>Try another source above.'],
  dayOnlyRange: ['Этот источник даёт на этот день только максимум и минимум.',
                 'For this day this source gives only the high and the low.'],
};
const t = (k) => (STR[k] || [k, k])[EN];
const tf = (k, ...a) => t(k).replace(/%(\d)/g, (_, i) => a[i - 1]);

// A condition, in English, is named from its icon key: the reading of the
// source's phrase that the server has already checked.
const COND = { 'clear': 'Clear', 'partly': 'Partly cloudy', 'cloudy': 'Cloudy',
  'overcast': 'Overcast', 'fog': 'Fog', 'drizzle': 'Drizzle', 'rain-light': 'Light rain',
  'rain': 'Rain', 'rain-heavy': 'Heavy rain', 'thunder': 'Thunderstorm', 'hail': 'Hail',
  'sleet': 'Sleet', 'snow-light': 'Light snow', 'snow': 'Snow', 'snow-heavy': 'Heavy snow' };
const cond = (x) => (!x ? '' : !EN ? x.condition || ''
  : COND[String(x.icon || '').replace('-night', '')] || '');
// The server's own words, Russian in, English out; the rest stays as said.
const RU_EN = { 'Яндекс': 'Yandex', 'утро': 'morning', 'день': 'afternoon',
  'вечер': 'evening', 'ночь': 'night', 'нет данных': 'no data',
  'не прочиталось': 'unreadable', 'заблокирован': 'blocked', 'не найдено': 'not found',
  'слишком часто': 'too many requests', 'сбой источника': 'source error',
  'недоступен': 'unavailable', 'нет ответа': 'no answer', 'другой город': 'wrong place',
  'нет города': 'city not covered', 'Нет сети и нет кэша': 'Offline, and nothing cached',
  'Ни один источник не отвечает, кэш пуст': 'No source is answering, and nothing is cached',
  'Слишком много запросов — попробуйте через минуту': 'Too many requests — try again in a minute' };
const en = (v) => (EN && v && RU_EN[v]) || v;
const PRECIP = { 'слабый дождь': 'Light rain', 'небольшой дождь': 'Light rain', 'дождь': 'Rain',
  'сильный дождь': 'Heavy rain', 'ливень': 'Downpour', 'морось': 'Drizzle',
  'слабый снег': 'Light snow', 'небольшой снег': 'Light snow', 'снег': 'Snow',
  'сильный снег': 'Heavy snow', 'мокрый снег': 'Sleet', 'дождь со снегом': 'Rain and snow',
  'град': 'Hail', 'гроза': 'Thunderstorm' };
/** Yandex's nowcast, in English when it has a known shape; else nothing. */
function nowcastText(s) {
  if (!EN || !s) return s;
  const x = s.replace(/\u2060/g, '').trim();
  if (/^Сегодня осадков не ожидается$/i.test(x)) return 'No precipitation expected today';
  const m = /^(.+?) с (\d\d?:\d\d) до (\d\d?:\d\d)$/.exec(x);
  const what = m && PRECIP[m[1].toLowerCase()];
  return what ? `${what}, ${m[2]}–${m[3]}` : null;
}
// The day's length and the magnetic field, as a source words them.
const MAG = { 'слабая буря': 'Minor storm', 'умеренная буря': 'Moderate storm',
  'сильная буря': 'Strong storm', 'очень сильная буря': 'Severe storm' };
function enValue(k, v) {
  if (!EN || !v) return v;
  if (k === 'daylight') {
    const m = /^(\d+)\s*ч\s*(\d+)\s*мин$/.exec(v);
    return m ? `${m[1]} h ${m[2]} min` : null;
  }
  // `c` is Latin in Yandex's «cлабая»: read as the letter it looks like.
  return MAG[v.toLowerCase().replace(/c/g, 'с')] || null;
}
/** A warning from the server, in English where it is one of the known ones. */
function warnText(w) {
  if (!EN) return w;
  const old = /^Данные устарели на (\d+) мин — ни один источник сейчас не отвечает$/.exec(w);
  if (old) return `Data is ${old[1]} min old — no source is answering right now`;
  const fb = /^(.+?): все поля получены запасным способом/.exec(w);
  if (fb) return `${en(fb[1])}: every field came from a fallback — the page has probably `
    + 'changed. The data still agrees, but the parser needs a look.';
  return en(w);
}
/** A place's name in the language on screen. */
const placeName = (p) => (!p ? '' : EN && p.name_en || p.name || '');

// `source` is the user's *preference*, remembered across cities and launches.
// It is not necessarily what is on screen: if the preferred source has no data
// for the city you just picked, we show one that does and leave the preference
// alone, so going back to a city it covers restores your choice.
let state = { place: null, data: null, source: null };

/* ------------------------------------------------------------------ utils */

const fmtT = (v) => {
  if (v === null || v === undefined) return '—';
  const m = Math.round(Math.abs(v));
  return (m && v > 0 ? '+' : m && v < 0 ? '−' : '') + m + '°';
};

const icon = (key, cls) =>
  `<svg class="${cls || ''}" aria-hidden="true"><use href="#i-${key || 'unknown'}"></use></svg>`;

const DOW = EN ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  : ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
const MON = EN ? ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
                  'Oct', 'Nov', 'Dec']
  : ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
// en-GB: day before month, and a 24-hour clock, like the Russian screen.
const LOCALE = EN ? 'en-GB' : 'ru-RU';

/** Today, as the *city* reckons it: `yyyy-mm-dd`. (`en-CA` formats that way.) */
function cityToday() {
  const tz = state.data && state.data.place && state.data.place.tz;
  try {
    return new Date().toLocaleDateString('en-CA', { timeZone: tz || undefined });
  } catch {
    return new Date().toLocaleDateString('en-CA');
  }
}

/** Whole days from today to `iso`, in the city's clock. */
function daysFromToday(iso) {
  // Both ends parsed as UTC noon, so the answer is a count of calendar days
  // and no daylight-saving transition can round it to the wrong one.
  return Math.round((Date.parse(iso + 'T12:00:00Z')
                     - Date.parse(cityToday() + 'T12:00:00Z')) / 86400000);
}

/* This used to take the row's *index* -- 0 was "Сегодня", 1 was "Завтра" --
 * and it was wrong in a way that only shows when you put two sources side by
 * side. The three do not agree on where their ten days start: Gismeteo's list
 * began on the 1st and Open-Meteo's on the 31st, so one screen called the 2nd
 * of August «Завтра» and the other called the same date «вс». Which of them
 * you believed depended on which tab you had open.
 *
 * The date is a fact and the position in an array is not. Same species as the
 * bug where the headline read the strip's first column and called it now. */
// `full`, for a sheet's title: a two-letter «пн» is a list cell, not a title.
function dayLabel(iso, full) {
  const d = new Date(iso + 'T12:00:00');
  const away = daysFromToday(iso);
  const f = (o) => d.toLocaleDateString(LOCALE, o);
  const w = full && f({ weekday: 'long' });
  const when = away === 0 ? t('today') : away === 1 ? t('tomorrow')
    : w ? w[0].toUpperCase() + w.slice(1) : DOW[d.getDay()];
  return { a: when, b: full ? f({ day: 'numeric', month: 'long' })
                            : `${d.getDate()} ${MON[d.getMonth()]}` };
}

function ago(iso) {
  const t = new Date(iso).getTime();
  if (!isFinite(t)) return '';
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  const hhmm = new Date(t).toLocaleTimeString(LOCALE,
    { hour: '2-digit', minute: '2-digit' });
  if (m < 1) return tf('updatedAt', hhmm);
  if (m < 60) return tf('minAgo', m, hhmm);
  return tf('hAgo', Math.round(m / 60), hhmm);
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

const num = (v) => (Math.round(v * 10) / 10).toString().replace('.', EN ? '.' : ',');
const shortTime = (t) => (t || '').includes('T') ? t.slice(11, 16) : (t || '');
const SHORT_DIR = { 'северный': 'С N', 'северо-восточный': 'СВ NE', 'восточный': 'В E',
  'юго-восточный': 'ЮВ SE', 'южный': 'Ю S', 'юго-западный': 'ЮЗ SW',
  'западный': 'З W', 'северо-западный': 'СЗ NW', 'штиль': 'штиль calm' };
const shortDir = (d) => (SHORT_DIR[d] ? SHORT_DIR[d].split(' ')[EN] : d || '');

/* ---- the sky ---------------------------------------------------------------
 * The hero sits on this rather than in a card. A box with four lines in it
 * reads as empty; the same four lines on a sky read as calm. Costs no extra
 * data, which was the constraint.
 *
 * Two mappings, and keeping them separate is the point. `SKY_OF` collapses
 * eighteen icons into seven **colours**, because a palette wants to be coarse
 * -- drizzle and a downpour are the same shade of grey and pretending
 * otherwise makes the app flicker between near-identical blues on every
 * refresh. `FX_OF` keeps all eighteen, because the *motion* is where the
 * difference lives: drizzle is thin and slow, a downpour is dense and fast,
 * and reading which one it is from across the room without focusing on a
 * number is the entire trick.
 *
 * Redrawn only when the effect actually changes -- a star field rebuilt on
 * every 10-minute refresh would flicker for no reason.
 */
const SKY_OF = {
  'clear': 'clear-day', 'clear-night': 'clear-night',
  'partly': 'cloudy-day', 'partly-night': 'cloudy-night',
  'cloudy': 'cloudy-day', 'cloudy-night': 'cloudy-night',
  'overcast': 'overcast', 'fog': 'overcast',
  'drizzle': 'rain', 'rain-light': 'rain', 'rain': 'rain',
  'rain-heavy': 'rain', 'thunder': 'rain', 'hail': 'rain',
  'snow-light': 'snow', 'snow': 'snow', 'snow-heavy': 'snow', 'sleet': 'snow',
};

/* Which layers each sky is built from, back to front.
 *
 * **There used to be a cloud layer here and it is gone, twice reported and
 * twice mis-fixed.** It was a handful of radial gradients -- soft light blobs
 * meant to read as cloud with a parallax behind them. On a desk they looked
 * fine. On the phone, in standalone mode with the sky running the full 852pt,
 * they read as a spotlight left on: a bright patch high on the screen with a
 * visible edge above it, worse than the plain gradient it replaced.
 *
 * The second attempt spread them over the whole box and cleared the top few
 * per cent so nothing crossed the status bar. That produced a *different*
 * edge, in a different place, and the person looking at the actual device said
 * plainly that it was worse than before. Two goes is enough: a localised bright
 * shape on a gradient is a hard thing to place blind, and the harness here
 * renders it correctly, which means the harness cannot referee it.
 *
 * What replaces it has **no spatial structure at all** -- a flat tint whose
 * only variable is opacity, breathing over ten seconds or so. It cannot make
 * an edge anywhere, because it is the same everywhere. That is a smaller idea
 * than parallax cloud and it is the one that survives contact with a device
 * nobody here can see.
 *
 * `*` used to mark a layer that differed after dark. Nothing left needs it:
 * the drops carry their own night colour and a flat tint has nothing to vary.
 */
const FX_OF = {
  'clear':        ['g sun'],
  'clear-night':  ['g moon', 'stars'],
  'partly':       ['h thin'],
  'partly-night': ['stars', 'h thin'],
  'cloudy':       ['h'],
  'cloudy-night': ['h'],
  'overcast':     ['h thick'],
  'fog':          ['b'],
  'drizzle':      ['p rain thin'],
  'rain-light':   ['p rain thin', 'p rain close'],
  'rain':         ['p rain', 'p rain close'],
  'rain-heavy':   ['p rain hard', 'p rain close'],
  'thunder':      ['p rain hard', 'p rain close'],
  'hail':         ['p hail'],
  'sleet':        ['p rain thin', 'p snow slow'],
  'snow-light':   ['p snow slow'],
  'snow':         ['p snow', 'p snow fast'],
  'snow-heavy':   ['p snow', 'p snow fast'],
};

let skyNow = null;
let fxNow = null;

/** Deterministic star field. One that jumps around between renders is worse
 *  than no star field. */
function starField() {
  let s = '';
  for (let i = 0; i < 60; i++) {
    s += `<circle cx="${((i * 37.7) % 100).toFixed(2)}%"
      cy="${((i * 61.3) % 62).toFixed(2)}%"
      r="${(0.5 + ((i * 13) % 7) / 9).toFixed(2)}" fill="#fff"
      style="animation-delay:${((i * 7) % 40) / 10}s"/>`;
  }
  return `<svg class="stars" width="100%" height="100%">${s}</svg>`;
}

function setSky(iconKey, night) {
  const kind = SKY_OF[iconKey] || 'cloudy-night';
  if (kind !== skyNow) {
    skyNow = kind;
    document.documentElement.dataset.sky = kind;  // <html> paints the canvas
    // Keep the status bar, the app-switcher card and the notch fill matching
    // the top of the gradient. One source of truth: whatever CSS resolved
    // `--sky1` to.
    setThemeColor(getComputedStyle(document.documentElement)
      .getPropertyValue('--sky1').trim());
  }

  // The night flag is the server's, from solar position -- not `hour > 20`.
  // Only clear/partly/cloudy carry it in the icon itself; rain at midnight is
  // still spelled `rain`, so without this the drops would be lit for noon.
  const fx = (FX_OF[iconKey] ? iconKey : 'cloudy-night') + (night ? '/n' : '');
  if (fx === fxNow) return;
  fxNow = fx;
  // On the root, not on the layers: the drops are the only thing that changes
  // after dark now, and one attribute the stylesheet keys off beats a class
  // threaded through a lookup table.
  document.documentElement.toggleAttribute('data-night', !!night);
  $('fx').innerHTML = (FX_OF[iconKey] || FX_OF['cloudy-night'])
    .map((l) => (l === 'stars' ? starField() : `<i class="${l}"></i>`))
    .join('');
}

/* --------------------------------------------------------------- rendering */

function chooseSource(key) {
  state.source = key;
  try { localStorage.setItem(LS.source, key); } catch (e) { /* private mode */ }
}

function pickSource(d) {
  const order = window.YW_SOURCES || ['yandex', 'gismeteo', 'openmeteo'];
  const has = (k) => d.sources && d.sources[k] && d.sources[k].available;
  if (state.source && has(state.source)) return state.source;
  if (d.selected && has(d.selected)) return d.selected;
  return order.find(has) || null;
}

function sourceStrip(d, active, date) {
  const order = window.YW_SOURCES || ['yandex', 'gismeteo', 'openmeteo'];
  const tabs = order.map((k) => {
    const s = (d.sources || {})[k];
    if (!s) return '';
    // The temperature on each tab is the whole point of having three: you see
    // the disagreement without switching, and judge it yourself. An
    // unavailable source keeps its seat, greyed, with the short reason -- a
    // tab that vanishes teaches you nothing.
    // On a day's sheet, that day's range: "+9°" now beside a sheet about
    // Thursday's +22° compared the wrong two things.
    const day = date && dayOn(s, date);
    const val = !s.available ? (en(s.reason) || t('noData'))
      : date ? (day ? `${fmtT(day.temp_max_c)} / ${fmtT(day.temp_min_c)}` : '—')
      : s.current && s.current.temp_c != null ? fmtT(s.current.temp_c) : t('noData');
    return `<button class="src ${k === active ? 'sel' : ''}" data-src="${esc(k)}"
      role="tab" aria-selected="${k === active}" ${s.available ? '' : 'disabled'}
      title="${esc(en(s.reason) || '')}">${esc(en(s.label))}<b>${esc(val)}</b></button>`;
  }).join('');
  return `<div class="srcs" id="srcs" role="tablist">${tabs}</div>`;
}

/* ---- the hourly curve ------------------------------------------------------
 * A row of numbers has to be read one at a time; a line is understood at a
 * glance, and "is it getting warmer or colder" is the actual question. The
 * label rides the curve rather than sitting in a fixed row, so the shape is
 * legible even before you read a single figure.
 *
 * The stroke runs through a vertical gradient -- warm at the top of the band,
 * cool at the bottom -- so colour reinforces height instead of decorating it.
 */
function hourOf(t) {
  const m = /(?:^|T)(\d{1,2}):/.exec(t || '');
  return m ? parseInt(m[1], 10) : null;
}

/** The current hour where the weather is, not where the phone is. */
function cityHour() {
  const tz = state.data && state.data.place && state.data.place.tz;
  try {
    return parseInt(new Date().toLocaleString('en-GB', {
      timeZone: tz || undefined, hour: '2-digit', hour12: false }), 10);
  } catch {
    return new Date().getHours();
  }
}

function hourWidth() {
  // From :root, so it resolves before the strip has been inserted.
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue('--hour-w').trim();
  const w = parseFloat(raw);
  return w > 0 ? w : 58;
}

function hourlyBlock(hours, nowcast, opts) {
  // `markNow` is false on a day-detail screen for any day but today. Without
  // it the strip labels 14:00 next Thursday "сейчас", because the only test
  // was that the hour number matched -- the same class of mistake as comparing
  // two times without saying which day they are on, which `series.py` exists
  // to stop happening on the server.
  const o = opts || {};
  const markNow = o.markNow !== false;
  const said = nowcastText(nowcast);
  const summary = said
    ? `<div class="nowcast">${icon('umbrella')}<span>${esc(said)}</span></div>` : '';
  const list = (hours || []).slice(0, o.limit || 24).filter((h) => h.temp_c != null);
  if (list.length < 2) {
    return summary ? `<div class="card">${summary}</div>` : '';
  }

  // Column width comes from the stylesheet (--hour-w) rather than being
  // restated here. The two disagreed once -- 58px there, 54px here -- and the
  // symptom was not what a wrong constant usually looks like: the curve
  // drifted 4px left per column and simply stopped short of the last labels.
  const W = hourWidth(), TOP = 24, BOT = 64, H = 72;
  // 6° of band at least, centred: fitted, a 1° step filled all 40px and ran
  // through the next label, and a flat day lay on the floor.
  const temps = list.map((h) => h.temp_c);
  const lo = Math.min(...temps), hi = Math.max(...temps);
  const span = Math.max(hi - lo, 6), min = (hi + lo - span) / 2;
  const y = (t) => BOT - ((t - min) / span) * (BOT - TOP);
  const width = list.length * W;

  const pts = list.map((h, i) => [i * W + W / 2, y(h.temp_c)]);
  const line = pts.map((p) => `${p[0]},${p[1].toFixed(1)}`).join(' ');
  const area = `${pts[0][0]},${H} ${line} ${pts[pts.length - 1][0]},${H}`;

  const svg = `<svg class="hcurve" width="${width}" height="${H}"
      viewBox="0 0 ${width} ${H}" aria-hidden="true">
    <defs>
      <!-- userSpaceOnUse, not the objectBoundingBox default. A bounding box
           has zero height when every hour is the same temperature, and a
           gradient over a zero-height box makes the element vanish entirely --
           so a flat forecast would render no line at all. This also makes the
           colour absolute: the same temperature is the same colour at both
           ends of the curve.
           The colours are the stylesheet's, by var() rather than restated:
           they were copies of --hot, --cold and --accent, so the light
           scheme's deeper blue reached the bars and never the curve. -->
      <linearGradient id="tgrad" gradientUnits="userSpaceOnUse"
                      x1="0" y1="${TOP}" x2="0" y2="${BOT}">
        <stop offset="0" style="stop-color:var(--hot)"/>
        <stop offset="1" style="stop-color:var(--cold)"/>
      </linearGradient>
      <linearGradient id="tfill" gradientUnits="userSpaceOnUse"
                      x1="0" y1="${TOP}" x2="0" y2="${H}">
        <stop offset="0" style="stop-color:var(--accent)" stop-opacity=".22"/>
        <stop offset="1" style="stop-color:var(--accent)" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <polygon points="${area}" fill="url(#tfill)"/>
    <polyline points="${line}" fill="none" stroke="url(#tgrad)" stroke-width="2.2"
              stroke-linejoin="round" stroke-linecap="round"/>
    ${pts.map((p) => `<circle cx="${p[0]}" cy="${p[1].toFixed(1)}" r="2.4"
        fill="var(--card)" stroke="url(#tgrad)" stroke-width="1.6"/>`).join('')}
  </svg>`;

  // "сейчас" only when it is. The first column is not automatically now: a
  // source may hand back a strip that starts at midnight, or at the next whole
  // hour, and labelling whatever comes first as the present moment is how the
  // app ended up describing 00:00 as the current conditions. Compared in the
  // *city's* clock, not the phone's -- the whole point is that you can look up
  // Moscow from anywhere.
  const nowHour = cityHour();
  // By instant where the source stamps its hours: matching the hour number
  // alone put «сейчас» on yesterday's 22:00 when the app opened offline the
  // next evening. Yandex's hours carry no date and keep the hour comparison.
  const sec = Date.now() / 1e3;
  const atNow = list.findLastIndex((h) => h.at <= sec && sec - h.at < 3600);
  const cols = list.map((h, i) => {
    const isNow = markNow && (h.at != null ? i === atNow
      : nowHour !== null && hourOf(h.time) === nowHour);
    return `<div class="hour${isNow ? ' now' : ''}">
      <div class="gz"><span class="hv" style="top:${(y(h.temp_c) - 20).toFixed(1)}px"
        >${fmtT(h.temp_c)}</span></div>
      ${icon(h.icon, 'wi')}
      <div class="hh">${esc(isNow ? t('now') : shortTime(h.time))}</div>
      <div class="hp">${h.precip_prob ? Math.round(h.precip_prob) + '%'
        : h.precip_mm ? esc(num(h.precip_mm)) + ' ' + t('mm') : ''}</div>
    </div>`;
  }).join('');

  return `<div class="card">${summary}<h2>${esc(o.title || t('hourly'))}</h2>
    <div class="hours"><div class="hstrip" style="width:${width}px">
      ${svg}${cols}
    </div></div></div>`;
}

/* ---- the ten-day list ------------------------------------------------------
 * Each row's bar shows where that day's low-to-high sits inside the whole
 * period's range. That is the comparison you are actually making when you scan
 * a forecast -- "is Thursday the cold one" -- and a bar answers it without
 * arithmetic. Today's row carries a dot at the current temperature.
 */
function dailyBlock(days, nowTemp) {
  const list = (days || []).filter((d) => d.temp_max_c != null);
  if (!list.length) return '';
  const today = cityToday();

  const lows = list.map((d) => d.temp_min_c).filter((v) => v != null);
  const highs = list.map((d) => d.temp_max_c);
  const wmin = Math.min(...lows, ...highs);
  const wmax = Math.max(...lows, ...highs);
  const span = (wmax - wmin) || 1;
  const pct = (t) => ((t - wmin) / span) * 100;

  const rows = list.map((d, i) => {
    const l = d.temp_min_c != null ? pct(d.temp_min_c) : 0;
    const r = pct(d.temp_max_c);
    // The dot marks where the current reading falls inside today's range,
    // so it belongs on the row that *is* today -- not on the first row. Two
    // of the three sources sometimes start their list on a different day.
    const dot = (d.date === today && nowTemp != null
                 && nowTemp >= wmin && nowTemp <= wmax)
      ? `<u style="left:${pct(nowTemp).toFixed(1)}%"></u>` : '';
    const lab = dayLabel(d.date);
    // A real <button>, not a div with a click handler: it is a control that
    // opens a screen, and the keyboard, the screen reader and the tap
    // highlight all follow from saying so.
    return `<button class="day" data-day="${esc(d.date)}">
      <div class="d">${esc(lab.a)}<small>${esc(lab.b)}</small></div>
      ${icon(d.icon, 'wi')}
      <span class="lo">${fmtT(d.temp_min_c)}</span>
      <div class="bar"><i style="left:${l.toFixed(1)}%;width:${Math.max(r - l, 3).toFixed(1)}%"></i>${dot}</div>
      <span class="hi">${fmtT(d.temp_max_c)}</span>
      <svg class="go" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>
    </button>`;
  }).join('');

  const n = list.length;                // 1..16: no source gives 21 days
  const head = EN ? `${n}-day forecast`
    : `Прогноз на ${n} ${n < 2 ? 'день' : n < 5 ? 'дня' : 'дней'}`;
  return `<div class="card"><h2>${head}</h2>${rows}</div>`;
}

/* ---- the quiet strip -------------------------------------------------------
 * Wind, humidity and pressure had a third of the first screen in v1. Nobody
 * opens a weather app for the pressure. They live down here now, small, with
 * sunrise/sunset and UV alongside them.
 */
function factsBlock(c, today) {
  const cells = [];
  const add = (k, v, raw) => { if (v) cells.push(
    `<div class="fact"><div class="k">${esc(k)}</div>
      <div class="v">${raw ? v : esc(v)}</div></div>`); };

  // The direction rides along as a smaller suffix so the cell never wraps.
  add(t('wind'), c.wind_ms != null
    ? `${num(c.wind_ms)} ${t('ms')}${c.wind_dir ? `<small>, ${esc(shortDir(c.wind_dir))}</small>` : ''}`
    : null, true);
  add(t('humidity'), c.humidity_pct != null ? Math.round(c.humidity_pct) + '%' : null);
  add(t('pressure'), c.pressure_mmhg != null
    ? Math.round(c.pressure_mmhg) + ' ' + t('mmHg') : null);
  if (today) {
    add(t('sunrise'), today.sunrise);
    add(t('sunset'), today.sunset);
    add(t('uv'), today.uv_index != null ? num(today.uv_index) : null);
    add(t('water'), today.water_temp_c != null ? fmtT(today.water_temp_c) : null);
  }
  if (cells.length < 3) return '';
  // Whole rows only. Seven cells in a three-column grid leaves two empty boxes
  // staring at you, and the fix is to drop the least useful cell rather than
  // to invent filler for it.
  const whole = cells.slice(0, Math.floor(cells.length / 3) * 3);
  return `<div class="card"><h2>${t('details')}</h2>
    <div class="facts">${whole.join('')}</div></div>`;
}

function render(d) {
  if (!d || !d.sources) { renderError(d); return; }
  const active = pickSource(d);
  if (!active) { renderError(d); return; }

  const view = d.sources[active];
  const c = view.current;
  if (!c) { renderError(d); return; }

  // The day whose date *is* today, not whichever day the source listed first.
  // The hero's high/low and the sunrise below it are statements about today,
  // and a source whose ten days begin tomorrow would otherwise have made them
  // quietly about tomorrow instead. No `|| daily[0]`: that did it anyway.
  const today = dayOn(view, cityToday());
  const range = today && today.temp_max_c != null
    ? `<span class="hi">${fmtT(today.temp_max_c)}</span>`
      + ` / <span class="lo">${fmtT(today.temp_min_c)}</span>`
    : '';
  const feels = c.feels_like_c != null && Math.round(c.feels_like_c) !== Math.round(c.temp_c)
    ? tf('feelsLike', fmtT(c.feels_like_c)) : '';

  setSky(c.icon, !!d.night);

  const hero = `<div class="hero">
    <div class="ic">${icon(c.icon)}</div>
    <div class="t">${fmtT(c.temp_c)}</div>
    <div class="cond">${esc(cond(c))}</div>
    ${range ? `<div class="sub">${range}</div>` : ''}
    ${feels ? `<div class="feels">${feels}</div>` : ''}
  </div>${sourceStrip(d, active)}`;

  $('content').innerHTML = hero
    + hourlyBlock(view.hourly, view.nowcast)
    // Under the hourly card, never above the hero: the temperature stays first.
    + a2hsBlock()
    + dailyBlock(view.daily, c.temp_c)
    + factsBlock(c, today);
  // A city picked from search keeps the geocoder's spelling: the server only
  // learns its coordinates, and would transliterate «Париж» as Parizh.
  $('city').textContent = EN && state.place && state.place.adhoc && state.place.name_en
    || placeName(d.place);
  $('pin').style.visibility = (state.place && state.place.gps) ? '' : 'hidden';
  renderHealth(d, view);

  // A refresh landing while a detail screen is open must reach that
  // screen too. Otherwise the numbers behind it move and the ones in front of
  // you do not, which is the app quietly showing two different forecasts at
  // once -- and the one you are looking at is the stale one.
  if (current && current.name === 'place') refreshPlaceList();   // keep the field
  else if (current) openScreen(current.name, current.arg);
}

function renderError(d) {
  // No reason here: «Что не так» below carries it, and the card repeated it.
  $('content').innerHTML = `<div class="card err">
    <p>${t('noWeather')}</p></div>`;
  if (d && d.place) $('city').textContent = placeName(d.place);
  if (d) renderHealth(d, null);
}

function renderHealth(d, view) {
  const h = d.health || {};
  const badge = $('badge');
  badge.className = 'badge ' + (h.status || 'ok');
  badge.textContent = ['degraded', 'stale', 'down'].includes(h.status) ? t(h.status) : '';
  // Down: «обновлено в 00:25» would claim the failed attempt as an update.
  $('stamp').textContent = h.status === 'down' ? '' : ago(d.fetched_at);

  const notes = $('notes');
  // Global problems, plus anything wrong with the source you are looking at.
  // Deliberately *not* "these sources disagree" -- all three temperatures are
  // on the tabs and you can judge that yourself.
  const msgs = (h.warnings || []).concat((view && view.warnings) || []).slice(0, 4);
  if (msgs.length) {
    notes.className = 'notes show';
    // Folded, since these lines are for the maintainer; open with no forecast.
    notes.innerHTML = `<details${view ? '' : ' open'}><summary>${t('whatsWrong')} · `
      + `${msgs.length}</summary><ul>${msgs.map((m) => `<li>${esc(warnText(m))}</li>`)
        .join('')}</ul></details>`;
  } else {
    notes.className = 'notes';
    notes.innerHTML = '';
  }
}

/* ------------------------------------------------------------------ data */

function placeQuery(p) {
  if (!p) return '';
  if (p.lat != null && p.lon != null && p.adhoc) return `lat=${p.lat}&lon=${p.lon}`;
  return `city=${encodeURIComponent(p.slug)}`;
}

// Newest request wins; `asked` keeps a pick alive through a refresh.
let loading = 0, asked = null;

async function load(place) {
  const want = asked = place || asked || state.place;
  const mine = ++loading;
  try {
    const q = placeQuery(want);
    const r = await fetch(`${BASE}api/weather?${q}`,
                          { headers: { 'Accept': 'application/json' } });
    const d = await r.json();
    if (mine !== loading) return;
    if (!r.ok && state.data && state.data.sources) return;   // a 503/404 is no forecast
    state.place = want;
    state.data = d;
    // On a cold start we ask for nothing and the server picks the default, so
    // adopt whatever it resolved -- otherwise the sheet has no idea which city
    // is current and shows no tick against any of them.
    if (!state.place && d.place) {
      state.place = { slug: d.place.slug, name: d.place.name, name_en: d.place.name_en,
                      lat: d.place.lat, lon: d.place.lon,
                      adhoc: !!d.place.ad_hoc };
    }
    try {
      localStorage.setItem(LS.payload, JSON.stringify(d));
      localStorage.setItem(LS.place, JSON.stringify(state.place));
    } catch (e) { /* private mode; the SW cache still covers us */ }
    render(d);
  } catch (e) {
    if (mine === loading && !state.data) renderError(null);
  }
}

/* --------------------------------------------------------------- geolocation
 *
 * A button, never automatic. Two reasons, and the second decided it:
 * home-screen web apps on iOS are reported not to persist the location
 * permission across refreshes, so an app that asks on every launch becomes an
 * app that prompts on every launch. And an app whose first screen needs a
 * permission is useless until you grant one -- Yoshkar-Ola loads instantly and
 * the button is there when you want it.
 *
 * Coordinates are rounded here, before transmission. ~1.1 km at two decimals,
 * far more precision than a forecast can use and far less than a location log
 * would want. The server rounds again.
 */
function useGeolocation() {
  if (!navigator.geolocation) { alert(t('geoNone')); return; }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const lat = +pos.coords.latitude.toFixed(PRECISION);
      const lon = +pos.coords.longitude.toFixed(PRECISION);
      load({ slug: `@${lat},${lon}`, name: '…', lat, lon, adhoc: true, gps: true });
      pop();
    },
    (err) => {
      alert(err.code === 1
        ? t('geoDenied') : t('geoFail'));
    },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 }
  );
}

/* ---- the navigation stack --------------------------------------------------
 *
 * One primitive, two screens: the day detail and the place picker. Both were
 * going to need "a thing that covers the app and can be dismissed", and two
 * implementations of that is how you end up with two subtly different back
 * behaviours.
 *
 * It is built on `history.pushState`, which is the whole point rather than an
 * implementation detail. In a standalone iOS PWA the edge-swipe-back gesture
 * is wired to browser history, so pushing a history entry is what makes the
 * screen dismissable by the system gesture -- and the OS animates that itself.
 *
 * Which is why nothing here acts on a *horizontal* touch: a hand-written
 * swipe runs *in addition to* the system gesture, and the app navigates back
 * twice. The sheet's vertical drag below collides with nothing (invariant 13).
 *
 * Depth is deliberately one. Neither screen leads anywhere else, and a stack
 * that can only ever hold one thing should say so rather than carry the
 * bookkeeping for a case that does not exist.
 */
const SCREENS = {};                 // name -> (arg) => {title, sub, html}
let current = null;                 // {name, arg} or null
let opener = null;

function pushMs() {
  // Read back from CSS rather than restated -- the same rule as --hour-w, and
  // for the same reason. CSS may spell a duration either way round, so both
  // are handled here rather than assumed at the other end.
  const raw = cssVar('--push-ms');
  const n = parseFloat(raw) || 0;
  return raw.endsWith('ms') ? n : raw.endsWith('s') ? n * 1000 : n;
}

/* ---- the sheet ------------------------------------------------------------
 *
 * A resizable bottom sheet with two detents, modelled on iOS's own
 * `UISheetPresentationController`. The CSS half is documented at `.screen`;
 * this is the half a stylesheet cannot do.
 *
 * Three behaviours are what separate a sheet that feels real from a panel that
 * animates, and all three are here:
 *
 *   - **The dimming tracks the drag.** Not "dim on open, undim on close" --
 *     the scrim's opacity is a function of where the sheet currently is, so
 *     the page behind brightens under your finger. Most of the illusion that
 *     you are moving an object lives in that one coupling.
 *   - **A flick is not a drag.** Past ~0.5 px/ms the sheet goes one detent the
 *     way you threw it regardless of where you let go; below that, it snaps to
 *     whichever detent is nearest. Position-only sheets feel sticky and
 *     velocity-only ones feel twitchy.
 *   - **The drag defers to the scroll.** At the large detent a drag may only
 *     begin at the top of the content, and a gesture that turns out to be
 *     horizontal is handed back -- the hourly curve inside the sheet scrolls
 *     sideways and must keep doing so.
 *
 * On invariant 13, deliberately: it forbids hand-rolling the *horizontal*
 * swipe, because iOS runs its own edge-swipe-back in a standalone PWA and a
 * second implementation makes the app navigate back twice. A vertical drag
 * does not collide with it. Dismissal still goes through `history.back()`, so
 * there remains exactly one way out and the system gesture still works.
 */
const DETENTS = ['large', 'mid', 'closed'];
const FLICK = 0.5;                  // px/ms; above this, direction beats position
let detent = 'mid';
let sheetY = 0;
let drag = null;

/** The sheet's own height. `offsetHeight`, not the rect: the rect is measured
 *  after the transform, and every detent is expressed against the untransformed
 *  box. Reading the wrong one makes the detents drift as the sheet moves. */
function sheetH() { return $('screen').offsetHeight || 1; }

function detentY(name) {
  if (name === 'large') return 0;
  if (name === 'closed') return sheetH();
  // Read back from CSS rather than restated -- `--sheet-mid` is the one place
  // the medium detent is written down. Same rule as `--hour-w` and
  // `--push-ms`, and the same test covers it.
  return sheetH() * (parseFloat(cssVar('--sheet-mid')) || 38) / 100;
}

function setSheet(y) {
  const h = sheetH();
  sheetY = Math.max(0, Math.min(y, h));
  $('screen').style.transform = `translateY(${sheetY}px)`;
  const shown = 1 - sheetY / h;
  // .62 at the large detent is about as dark as iOS goes; the fade over the
  // bottom of the viewport comes in with the sheet so it never sits over a
  // fully lit forecast.
  $('scrim').style.opacity = (0.62 * shown).toFixed(3);
  // Not `shown`. The fade has a job to do at *every* detent -- it is what stops
  // a card meeting the bottom of the view at a hard edge -- so it has to be
  // fully on by the time the sheet has arrived anywhere, not proportional to
  // how far up it went. It was proportional first, which left it at 62% at the
  // medium detent and put a measurable step back at the seam: (13,21,40)
  // against a canvas of (10,16,32). Ramped at twice the rate, it is complete
  // before the first detent and still fades out on the way to dismissed.
  $('sheetfade').style.opacity = Math.min(1, shown * 2).toFixed(3);
}

function goDetent(name) {
  // One way out, whichever gesture asked for it: the back button, the system
  // edge swipe, a tap on the scrim and a flick down all end up here, and here
  // it is always `history.back()`. Two dismissal paths is how a screen gets
  // left in the history stack.
  if (name === 'closed') { history.back(); return; }
  detent = name;
  $('screen').dataset.detent = name;
  setSheet(detentY(name));
}

function dragging(on) {
  for (const id of ['screen', 'scrim']) $(id).classList.toggle('dragging', on);
}

function onDragStart(e) {
  if (!current || e.touches.length !== 1) return;
  const body = $('screen-body');
  // At the medium detent nothing scrolls, so the whole surface is a handle. At
  // the large one a drag may only begin at the very top of the content --
  // otherwise the sheet moves when you meant to scroll the list, which is the
  // most annoying thing a hand-rolled sheet can do.
  const onBar = !!(e.target.closest && e.target.closest('.navbar'));
  if (!onBar && detent !== 'mid' && body.scrollTop > 0) return;
  const t = e.touches[0];
  drag = { x0: t.clientX, y0: t.clientY, base: sheetY,
           last: t.clientY, lastT: e.timeStamp, v: 0, moved: false };
}

/** Does this gesture belong to the sheet, or to something inside it?
 *
 *  Pulled out and named because getting it wrong is silent: the sheet simply
 *  swallows a gesture and whatever should have moved does not, with no error
 *  anywhere. Both ways of getting it wrong have shipped.
 *
 *  `dx > |dy|` — sideways is the hourly strip's, which scrolls horizontally.
 *
 *  `dy < 0 && atTop` — **upward at the largest detent is the content's.** The
 *  sheet has nowhere further to go, so claiming the gesture clamps it to 0 and
 *  `preventDefault`s the native scroll: a full-height sheet whose content is
 *  taller than it is becomes completely unscrollable. Reported as "it sticks
 *  to the top and not all of the detail is visible". This is also what iOS
 *  does — at the largest detent a sheet scrolls rather than resizes.
 *
 *  Exported on `window` for the tests, which drive it as a table rather than
 *  trying to synthesise touch sequences.
 */
function dragBelongsToSheet(dy, dx, atTop) {
  if (dx > Math.abs(dy)) return false;
  if (dy < 0 && atTop) return false;
  return true;
}
window.dragBelongsToSheet = dragBelongsToSheet;

function onDragMove(e) {
  if (!drag) return;
  const t = e.touches[0];
  const dy = t.clientY - drag.y0;
  if (!drag.moved) {
    const dx = Math.abs(t.clientX - drag.x0);
    if (Math.abs(dy) < 6 && dx < 6) return;
    if (!dragBelongsToSheet(dy, dx, drag.base <= 0)) { drag = null; return; }
    drag.moved = true;
    dragging(true);
  }
  if (e.cancelable) e.preventDefault();
  const dt = e.timeStamp - drag.lastT;
  if (dt > 0) drag.v = (t.clientY - drag.last) / dt;   // px/ms, + is downward
  drag.last = t.clientY;
  drag.lastT = e.timeStamp;
  // No overscroll upwards: the sheet's bottom is the bottom of the viewport,
  // and lifting it above the large detent would open a gap onto the canvas.
  setSheet(Math.max(0, drag.base + dy));
}

function onDragEnd() {
  if (!drag) return;
  const d = drag;
  drag = null;
  dragging(false);
  if (!d.moved) return;
  let next;
  if (Math.abs(d.v) > FLICK) {
    const i = DETENTS.indexOf(detent) + (d.v > 0 ? 1 : -1);
    next = DETENTS[Math.max(0, Math.min(DETENTS.length - 1, i))];
  } else {
    next = DETENTS.reduce((best, n) =>
      Math.abs(detentY(n) - sheetY) < Math.abs(detentY(best) - sheetY) ? n : best);
  }
  goDetent(next);
}

/** Renders `name` into the screen. Returns false when it has nothing to show,
 *  so the caller can decline to push a history entry for a blank screen. */
function openScreen(name, arg) {
  const spec = SCREENS[name](arg);
  if (!spec) return false;
  const already = current !== null;
  const body = $('screen-body');
  // Redrawing the *same* screen must not move it. `scrollTop` is kept rather
  // than zeroed, because this function also runs on every refresh and
  // on a source switch -- and a screen that jumps to the top while you are
  // reading it is worse than one showing a stale number. A different screen
  // starts at the top, as arriving somewhere new should.
  const at = already && current.name === name ? body.scrollTop : 0;
  current = { name, arg };
  $('screen-title').innerHTML = spec.title
    + (spec.sub ? `<small>${spec.sub}</small>` : '');
  body.innerHTML = spec.html;
  body.scrollTop = at;
  if (already) return true;

  opener = document.activeElement;
  $('screen').setAttribute('aria-hidden', 'false');
  for (const id of ['screen', 'scrim', 'sheetfade']) $(id).classList.add('open');
  // Parked off-screen and reflowed *before* the detent is set. Without the
  // reflow the browser coalesces both writes into one style change and the
  // sheet simply appears at its detent, having travelled nowhere.
  dragging(true);
  setSheet(sheetH());
  void $('screen').offsetHeight;
  dragging(false);
  goDetent('mid');
  document.querySelector('.wrap').inert = true;
  // Pin the page underneath -- `overflow: hidden` on the root, which changes
  // no geometry and therefore costs no reflow. It used to switch <body> to
  // `position: fixed` and juggle the scroll offset by hand, which relayouts
  // the whole document in the same task that starts the sheet's transition.
  // See the `html.locked` rule for what that did to the animation.
  document.documentElement.classList.add('locked');
  $('screen-title').focus({ preventScroll: true });
  return true;
}

function closeScreen() {
  setSheet(sheetH());
  for (const id of ['screen', 'scrim', 'sheetfade']) $(id).classList.remove('open');
  $('screen').setAttribute('aria-hidden', 'true');
  document.querySelector('.wrap').inert = false;
  // Nothing to restore: the document never moved.
  document.documentElement.classList.remove('locked');
  if (opener && opener.isConnected) opener.focus({ preventScroll: true });
  current = null;
  // Emptied only after it has finished sliding out, or the screen goes blank
  // in front of you for the length of the animation.
  setTimeout(() => { if (!current) $('screen-body').innerHTML = ''; }, pushMs());
}

function push(name, arg) {
  if (!SCREENS[name]) return;
  const stacking = current !== null;
  // Rendered before the history entry exists, so a screen with nothing to show
  // leaves no entry behind for the back gesture to land on.
  if (!openScreen(name, arg)) return;
  // Replace rather than stack when a screen is already up: depth stays one, so
  // the history is one entry deep whatever route got you here.
  if (stacking) history.replaceState({ yw: name, arg }, '');
  else history.pushState({ yw: name, arg }, '');
}

/** The in-app back control. Goes through history so it behaves identically to
 *  the system gesture -- one code path, one outcome. */
function pop() {
  if (current) history.back();
}

window.addEventListener('popstate', (e) => {
  const want = e.state && e.state.yw;
  if (!want) { if (current) closeScreen(); return; }
  if (!current || current.name !== want) openScreen(want, e.state.arg);
});

/* ---- the place picker ------------------------------------------------------
 * Search, geolocation and the saved cities are all answers to one question --
 * "where" -- so they live on one screen instead of three permanent strips. It
 * costs a tap on a decision made twice a month and gives the whole top of the
 * app back to the weather.
 */
let searchTimer = null;
let savedCities = [];
let found = [];

const GEO_ICON = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.2"/>'
  + '<circle cx="12" cy="12" r="8"/><path d="M12 1.5V4M12 20v2.5M1.5 12H4M20 12h2.5"/></svg>';
const TICK = '<svg class="tick" viewBox="0 0 24 24"><path d="M4 12.5l5 5L20 6.5"/></svg>';

/* Read a CSS custom property back rather than restating its value here. A
 * constant written down in two languages diverges; this file has the scars.
 */
function cssVar(name) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();
}

function setThemeColor(c) {
  const meta = document.getElementById('theme-color');
  if (meta && c) meta.setAttribute('content', c);
}

let lastQuery = '';

/* The field and the list are rendered separately, and that split is the whole
 * reason results can update while you type. Re-rendering the field along with
 * them would replace the element the keyboard is attached to -- on iOS that
 * closes the keyboard and drops the caret, once per keystroke. */
SCREENS.place = () => ({
  title: t('place'),
  html: `<input id="q" type="search" placeholder="${t('search')}"
           autocomplete="off" autocorrect="off" spellcheck="false"
           enterkeyhint="search" value="${esc(lastQuery)}">
         <div id="plist">${placeList()}</div>`,
});

function placeList() {
  const cur = state.place && state.place.slug;
  const onGps = !!(state.place && state.place.gps);
  const out = [];

  // An action, not a list item -- so it gets no container. Boxed, it echoed
  // the search field sitting right above it.
  if (window.YW_GEO !== false) out.push(`<button class="geolink" data-act="geo">${GEO_ICON}
    <span>${t('myLoc')}</span>
    ${onGps ? `<span class="on">${t('on')}</span>` : ''}</button>`);

  if (lastQuery.trim().length >= 2) {
    out.push(`<h3>${t('found')}</h3>`);
    if (!found.length) {
      out.push(`<div class="empty">${t('nothing')}</div>`);
    } else {
      out.push('<ul class="group">' + found.map((p, i) =>
        `<li data-find="${i}"><button class="nm">${esc(placeName(p))}</button>
          <span class="sub">${esc((EN ? p.subtitle_en : p.subtitle) || '')}</span></li>`).join('')
        + '</ul>');
    }
  } else {
    out.push(`<h3>${t('cities')}</h3><ul class="group">` + savedCities.map((c) =>
      `<li data-slug="${esc(c.slug)}" class="${c.slug === cur && !onGps ? 'sel' : ''}">
        <button class="nm">${esc(placeName(c))}</button>
        ${c.slug === cur && !onGps ? TICK : ''}</li>`).join('') + '</ul>');
  }
  return out.join('');
}

function refreshPlaceList() {
  const list = $('plist');
  if (list) list.innerHTML = placeList();
}

async function doSearch(q) {
  lastQuery = q;
  if (q.trim().length < 2) { found = []; refreshPlaceList(); return; }
  try {
    const r = await fetch(`${BASE}api/search?q=${encodeURIComponent(q)}`);
    const got = (await r.json()).results || [];
    if (q !== lastQuery) return;
    found = got;
    refreshPlaceList();
  } catch (e) { /* offline: leave the last results up */ }
}

async function loadCities() {
  try {
    const r = await fetch(`${BASE}api/cities`);
    savedCities = (await r.json()).cities || [];
  } catch (e) { /* ignore */ }
}

/* ---- the day detail --------------------------------------------------------
 *
 * Keyed by *date*, never by index. The tab strip is live on this screen, and
 * three sources do not necessarily start their ten days on the same morning --
 * so an index would quietly show you a different day when you switched source,
 * which is the wrong-cell failure this codebase spends most of its effort on,
 * committed by the front end for a change.
 */
function dayOn(view, date) {
  return ((view && view.daily) || []).find((d) => d.date === date) || null;
}

/** The hours belonging to one calendar day, for the sources that can say.
 *
 *  Open-Meteo stamps every entry with a full ISO local time, so slicing is
 *  exact. Gismeteo ships a UTC epoch, which needs the city's clock to decide
 *  which day it lands in. Yandex ships «21:00» and nothing else -- no date, no
 *  epoch -- so for Yandex this returns nothing rather than guessing, and the
 *  screen falls back to the parts of day, which is Yandex's own shape anyway.
 */
function hoursOn(hours, date, tz) {
  return (hours || []).filter((h) => {
    if (typeof h.time === 'string' && h.time.length >= 10 && h.time.includes('T')) {
      return h.time.slice(0, 10) === date;
    }
    if (h.at == null) return false;
    try {
      return new Date(h.at * 1000).toLocaleDateString('en-CA',
        { timeZone: tz || undefined }) === date;   // en-CA renders as yyyy-mm-dd
    } catch { return false; }
  });
}

/* Source order, deliberately not sorted.
 *
 * The first version sorted these into ночь → утро → день → вечер, on the
 * reasoning that a day starts at midnight. Yandex prints them утро → день →
 * вечер → ночь, and its «ночь» column is the night that *follows* the day.
 * Sorting therefore did not tidy the list, it moved a forecast twenty-four
 * hours: the row labelled «ночь» at the top of Tuesday would have been
 * Tuesday-into-Wednesday presented as Monday-into-Tuesday.
 *
 * Nothing about that is visible -- four plausible temperatures in a plausible
 * order. Reordering data asserts a fact about what the order meant, and that
 * fact had not been checked. The source knows what its own columns are.
 */
function partsBlock(day) {
  if (!day.parts || !day.parts.length) return '';
  const rows = day.parts
    .map((p) => {
      const bits = [];
      if (p.wind_ms != null) {
        // Gusts ride along with the wind rather than getting a cell of their
        // own: "3 м/с, порывы до 8" is one fact about how it will feel outside, and
        // the gust alone means nothing without the speed beside it.
        const gust = p.wind_gust_ms != null && p.wind_gust_ms > p.wind_ms
          ? ', ' + tf('gustsTo', num(p.wind_gust_ms)) : '';
        bits.push(`${num(p.wind_ms)} ${t('ms')}${gust}${p.wind_dir ? ', ' + shortDir(p.wind_dir) : ''}`);
      } else if (p.wind_dir === 'штиль') {
        // Gismeteo publishes a direction of «штиль» and *no speed at all* for
        // a calm part of the day. Gating the whole cell on the speed dropped
        // the one reading that says something -- the row simply lost its wind.
        bits.push(shortDir('штиль'));
      }
      if (p.precip_mm) bits.push(num(p.precip_mm) + ' ' + t('mm'));
      // No humidity or pressure: a bare "91%" under «Небольшой дождь» read as
      // its chance, and 744/745/745/745 says nothing about a morning.
      const feels = p.feels_like_c != null
        && Math.round(p.feels_like_c) !== Math.round(p.temp_c)
        ? tf('feels', fmtT(p.feels_like_c)) : '';
      return `<div class="part">
        <div class="n">${esc(en(p.name))}</div>
        ${icon(p.icon, 'wi')}
        <div class="tt">${fmtT(p.temp_c)}</div>
        <div class="m"><b>${esc(cond(p))}</b>
          ${esc([...bits, feels].filter(Boolean)
            .map((b) => b.replace(/ /g, '\u00a0')).join(' · '))}</div>
      </div>`;
    }).join('');
  return `<div class="card"><h2>${t('parts')}</h2>${rows}</div>`;
}

function metricsBlock(day) {
  const rows = [];
  const add = (k, v, unit) => {
    if (v === null || v === undefined || v === '') return;
    rows.push(`<div class="metric"><div class="k">${esc(k)}</div>
      <div class="v">${esc(v)}${unit ? `<small>${esc(unit)}</small>` : ''}</div></div>`);
  };
  const range = (a, b) => (a == null || b == null || a === b)
    ? (a == null ? b : a) : `${a}–${b}`;

  if (day.feels_min_c != null || day.feels_max_c != null) {
    add(t('feelsRange'), day.feels_min_c != null && day.feels_max_c != null
      ? `${fmtT(day.feels_min_c)} … ${fmtT(day.feels_max_c)}`
      : fmtT(day.feels_max_c != null ? day.feels_max_c : day.feels_min_c));
  }
  if (day.avg_temp_c != null) add(t('avg'), fmtT(day.avg_temp_c));
  // Unit immediately after the number, direction after the unit. Written the
  // other way round it reads "3 З м/с", and Cyrillic З next to a digit is a 3
  // at a glance -- the cell said "3 3 м/с" and I had to look twice.
  if (day.wind_ms != null) {
    add(t('wind'), num(day.wind_ms),
        ` ${t('ms')}${day.wind_dir ? ', ' + shortDir(day.wind_dir) : ''}`);
  } else if (day.wind_dir) {
    add(t('wind'), shortDir(day.wind_dir));
  }
  if (day.wind_gust_ms != null) add(t('gusts'), num(day.wind_gust_ms), ' ' + t('ms'));
  if (day.humidity_pct != null) add(t('humidity'), Math.round(day.humidity_pct), '%');
  const p = range(day.pressure_min_mmhg != null ? Math.round(day.pressure_min_mmhg) : null,
                  day.pressure_max_mmhg != null ? Math.round(day.pressure_max_mmhg) : null);
  if (p != null) add(t('pressure'), p, ' ' + t('mmHg'));
  if (day.precip_mm != null) add(t('precip'), num(day.precip_mm), ' ' + t('mm'));
  if (day.precip_prob != null) add(t('precipProb'), Math.round(day.precip_prob), '%');
  if (day.snow_cm) add(t('snow'), num(day.snow_cm), ' ' + t('cm'));
  if (day.snow_depth_cm) add(t('snowDepth'), num(day.snow_depth_cm), ' ' + t('cm'));
  if (day.uv_index != null) add(t('uv'), num(day.uv_index));
  if (day.kp_index != null) add(t('kp'), num(day.kp_index), ' Kp');
  if (day.water_temp_c != null) add(t('water'), fmtT(day.water_temp_c));
  if (day.sunrise) add(t('sunrise'), day.sunrise);
  if (day.sunset) add(t('sunset'), day.sunset);
  if (day.daylight) add(t('daylight'), enValue('daylight', day.daylight));
  if (day.magnetic) add(t('magnetic'), enValue('magnetic', day.magnetic));
  if (!rows.length) return '';
  return `<div class="card"><h2>${t('details')}</h2>${rows.join('')}</div>`;
}

/* ---- the deeper day, fetched when you open one -----------------------------
 *
 * Yandex publishes a page per day, so ten days would be ten requests against
 * the one this app spends per source per city per ten minutes. The trade is:
 * ask for exactly the day somebody opened, and treat the answer as an upgrade
 * rather than a dependency.
 *
 * Which is why there is no spinner. The screen renders immediately from the
 * payload already in hand -- four parts of day, the metric table -- and the
 * eight-column curve appears underneath it a moment later if the network
 * cooperates. Offline, or upstream down, the screen is exactly what it was
 * before this existed. A loading state would be advertising a thing that may
 * not arrive, in place of a thing that already has.
 */
const deeper = {};                   // "kazan|yandex|2026-08-07" -> Day, or null

const deepKey = (source, date) =>
  `${state.data && state.data.place && state.data.place.slug}|${source}|${date}`;

/** The set fields of an object. Merging the deep day over the shallow one has
 *  to skip its blanks, or a page that omits a value would *erase* one the main
 *  payload had — an upgrade that takes things away is not an upgrade. */
function pickTruthy(obj) {
  const out = {};
  for (const k in obj) if (obj[k] !== null && obj[k] !== undefined) out[k] = obj[k];
  return out;
}

async function fetchDeeper(source, date) {
  const key = deepKey(source, date);
  if (key in deeper) return;         // in flight, fetched, or known absent
  deeper[key] = null;
  try {
    const r = await fetch(`${BASE}api/day?date=${encodeURIComponent(date)}`
      + `&${placeQuery(state.place)}`);
    // 204 means the server looked and there is no page for this day -- a GPS
    // fix, or a date past the tenth. That is an answer, so it is remembered;
    // asking again would be one wasted request per redraw.
    if (r.status === 204) return;
    if (!r.ok) { delete deeper[key]; return; }
    const got = await r.json();
    if (!got.day || !(got.day.hours || []).length) return;
    deeper[key] = got.day;
    // Only redraw if you are still looking at the day it was fetched for.
    if (current && current.name === 'day' && current.arg === date) {
      openScreen('day', date);
    }
  } catch (e) {
    // Offline, or the request failed. Forget it rather than remembering a
    // failure: the screen is complete without this, and the next time you
    // open the day you may well have signal.
    delete deeper[key];
  }
}

SCREENS.day = (date) => {
  const d = state.data;
  if (!d || !d.sources) return null;
  const active = pickSource(d);
  const view = d.sources[active];
  const day = dayOn(view, date);
  const i = ((view && view.daily) || []).findIndex((x) => x.date === date);
  const lab = dayLabel(date, 1);
  const tz = d.place && d.place.tz;

  const foot = () => `<p class="screenfoot">${esc(view ? en(view.label) : '')}`
    + `${d.fetched_at ? ' · ' + ago(d.fetched_at) : ''}</p>`;

  let body = sourceStrip(d, active, date);
  if (!day) {
    body += `<div class="card nodata">${tf('dayNoData', esc(view ? en(view.label) : ''))}</div>`;
    return { title: lab.a, sub: lab.b, html: body + foot() };
  }

  const range = day.temp_max_c != null
    ? `<span class="hi">${fmtT(day.temp_max_c)}</span> / `
      + `<span class="lo">${fmtT(day.temp_min_c)}</span>` : '';
  body += `<div class="dayhero">${icon(day.icon)}
    <div><div class="r">${range}</div>
      <div class="c">${esc(cond(day))}</div></div></div>`;

  // Each source in the shape it is actually good at, ordered by how much of
  // the day each block answers at once. Four named parts summarise a day
  // better than anything else here, so they lead when a source has them --
  // Yandex off its ten-day page, Gismeteo off /3-days/. Open-Meteo has none
  // and leads with the hour-by-hour curve, which for any date but today is
  // the only one it can draw at all. Metrics come last everywhere: they are
  // what you go looking for, not what you glance at.
  // The per-day page, when this source has one and it has arrived. Eight
  // three-hourly columns with feels-like and gusts beat whatever slice of the
  // flat series happens to fall on this date, so it wins where it exists.
  const deep = deeper[deepKey(active, date)];
  if (active === 'yandex' && !deep) fetchDeeper(active, date);
  const hours = (deep && deep.hours) || hoursOn(view.hourly, date, tz);
  const curve = hours.length >= 2
    ? hourlyBlock(hours, null, { title: t('hourly'),
                                 markNow: date === cityToday() }) : '';
  const parts = partsBlock(day);
  const metrics = metricsBlock(deep ? { ...day, ...pickTruthy(deep) } : day);
  body += [parts, curve, metrics].join('');

  if (!parts && !curve && !metrics) {
    body += `<div class="card nodata">${t('dayOnlyRange')}</div>`;
  }
  return { title: lab.a, sub: lab.b, html: body + foot() };
};

/* ---- the home-screen banner (DECISIONS.md §35) -----------------------------
 * Only where an install can happen and has not: Safari outside the home screen
 * (`navigator.standalone` exists in iOS WebKit alone), or a browser that has
 * handed us `beforeinstallprompt`, whose prompt is then a one-tap install. */
Object.assign(STR, {
  a2hsTitle: ['Добавьте значок на\u00a0экран «Домой»', 'Add the icon to your Home\u00a0Screen'],
  a2hsApp: ['Установите «Погоду» как приложение', 'Install Weather as an app'],
  a2hsHow: ['Как добавить', 'Show Me How'],
  a2hsInstall: ['Установить', 'Install'],
  a2hsNo: ['Больше не предлагать', 'Don’t suggest this again'],
  a2hsSheet: ['На экран «Домой»', 'Add to Home Screen'],
  a2hsIn: ['в Safari', 'in Safari'],
  a2hsWhy: ['«Погода» откроется на\u00a0весь экран, без\u00a0панелей Safari, и\u00a0покажет'
    + ' последний прогноз даже без\u00a0интернета.',
  'It opens full screen, without Safari’s bars, and shows the last forecast even offline.'],
  a2hsStep1: ['Нажмите <b>⋯</b> справа от адресной строки', 'Tap <b>⋯</b> next to the address bar'],
  a2hsStep2: ['Выберите «Поделиться»', 'Tap <b>Share</b>'],
  a2hsStep3: ['Пролистайте вниз и\u00a0выберите «На\u00a0экран „Домой“»',
    'Scroll down and tap <b>Add to Home Screen</b>'],
  // Not the switch's Russian name, which is unconfirmed; it is the only one there.
  a2hsStep4: ['Оставьте переключатель включённым и\u00a0нажмите «Добавить»',
    'Make sure <b>Open as Web App</b> is on, then tap <b>Add</b>'],
  a2hsOld: ['До iOS\u00a026 кнопка «Поделиться»\u00a0— прямо на\u00a0панели\u00a0Safari.',
    'Before iOS\u00a026, <b>Share</b> is right in Safari’s toolbar.'],
});
LS.a2hs = 'yw.a2hs';
let bip = null;                     // a held `beforeinstallprompt`: one tap installs
let a2hsOff = false;                // dismissed this visit, even if storage is not

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  bip = e;
  if (state.data) render(state.data);
});
window.addEventListener('appinstalled', () => { a2hsOff = true; a2hsDrop(); });

function a2hsWanted() {
  try { if (localStorage.getItem(LS.a2hs) === 'no') return false; } catch (e) { /* blocked */ }
  if (a2hsOff || matchMedia('(display-mode: standalone)').matches) return false;
  return !!bip || navigator.standalone === false;
}

function a2hsBlock() {
  if (!a2hsWanted()) return '';
  return `<div class="card a2hs" role="region" aria-labelledby="a2t">
    <div class="ph" aria-hidden="true"><svg class="st" viewBox="0 0 31 9"><path d="M0
      9h2V6.5H0zm3 0h2V5H3zm3 0h2V3H6zm3 0h2V1H9zm5-5a6.4 6.4 0 0 1 9 0L18.5 8.5z"/>
      <rect x="24" y="1.5" width="7" height="6" rx="1.8"/></svg><div class="g"><i></i><i></i>
      <i></i><i></i><i></i><b>${icon('partly')}</b></div></div>
    <div class="tx"><p id="a2t">${t(bip ? 'a2hsApp' : 'a2hsTitle')}</p><button class="go"
      data-act="a2hs">${t(bip ? 'a2hsInstall' : 'a2hsHow')}</button></div>
    <button class="x" data-act="a2hs-no" aria-label="${t('a2hsNo')}"><svg viewBox="0 0 12 12"
      aria-hidden="true"><path d="M1 1l10 10M11 1 1 11"/></svg></button></div>`;
}

function a2hsDrop() {
  const b = document.querySelector('.a2hs');
  if (b) b.remove();
}

function a2hsGo() {
  const e = bip;
  if (!e) { push('install'); return; }
  // One prompt per event; the browser sends another if it will ask again.
  bip = null;
  e.prompt();
  e.userChoice.then(a2hsDrop, a2hsDrop);
}

function a2hsNo() {
  a2hsOff = true;
  try { localStorage.setItem(LS.a2hs, 'no'); } catch (e) { /* blocked: this visit only */ }
  a2hsDrop();
}

// Safari's glyph for each step, so a row can be matched to its button.
const A2G = ['<circle cx="12" cy="12" r="9.5"/><path d="M7.5 12h0M12 12h0M16.5 12h0" stroke-width="2.6"/>',
  '<path d="M8.5 9.5H6v11h12v-11h-2.5M12 3.5v11M8.5 7 12 3.5 15.5 7"/>',
  '<rect x="3.5" y="3.5" width="17" height="17" rx="4.5"/><path d="M12 8v8M8 12h8"/>',
  '<rect x="1.5" y="6" width="21" height="12" rx="6"/><path d="M16.5 12h0" stroke-width="7"/>'];

SCREENS.install = () => ({
  title: t('a2hsSheet'),
  sub: t('a2hsIn'),
  html: `<p class="a2why">${t('a2hsWhy')}</p><ol class="group a2steps">${A2G.map((g, i) =>
    `<li><svg viewBox="0 0 24 24" aria-hidden="true">${g}</svg><span>${t('a2hsStep' + (i + 1))}`
    + '</span></li>').join('')}</ol><p class="screenfoot">${t('a2hsOld')}</p>`,
});

/* ------------------------------------------------------------------- boot */

/** The words the static page carries, in the chosen language -- and the
 *  switch to the other one. A reload rather than a re-render: every string is
 *  read when it is drawn, and the shell is in the service worker, so the
 *  round trip is the cache's. */
function applyLang() {
  document.documentElement.lang = LANG;
  document.title = t('app');
  const meta = document.querySelector('meta[name="apple-mobile-web-app-title"]');
  if (meta) meta.content = t('app');
  // The name the home screen gives the app, if it is added from here.
  if (EN) document.querySelector('link[rel="manifest"]').href = 'manifest.webmanifest?lang=en';
  $('btn-refresh').textContent = t('refresh');
  $('close').setAttribute('aria-label', t('close'));
  $('pin').setAttribute('aria-label', t('gps'));
  const sr = document.querySelector('#content .sr');
  if (sr) sr.textContent = t('loading');
  const b = $('btn-lang');
  b.textContent = t('otherLang');
  b.lang = EN ? 'ru' : 'en';
  b.addEventListener('click', () => {
    try { localStorage.setItem(LS.lang, EN ? 'ru' : 'en'); } catch (e) { /* blocked */ }
    location.replace(location.pathname);
  });
}

function boot() {
  applyLang();
  // Paint whatever we had last, immediately, before any network happens.
  const get = (k) => { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } };
  state.place = get(LS.place);
  try { state.source = localStorage.getItem(LS.source); } catch (e) { /* blocked */ }
  try { if ((state.data = get(LS.payload))) render(state.data); } catch (e) { /* ignore */ }

  loadCities();
  load(state.place);

  // A screen open at load time is a reload *while* it was open. The payload
  // has not arrived yet and the day it referred to may not exist any more, so
  // the entry is rewritten rather than restored -- reopening it would mean
  // guessing, and guessing here shows you a different day than the one you
  // left.
  if (history.state && history.state.yw) history.replaceState(null, '');

  $('btn-place').addEventListener('click', () => push('place'));
  $('close').addEventListener('click', pop);
  // Tapping the dimmed page dismisses, the way iOS's dimming view does.
  $('scrim').addEventListener('click', pop);
  // Vertical only, and only while a sheet is up -- see the block above
  // `openScreen` for why this does not collide with the system's edge swipe.
  // Not passive: a drag that has claimed the gesture has to be able to stop
  // the page underneath from scrolling with it.
  $('screen').addEventListener('touchstart', onDragStart, { passive: true });
  $('screen').addEventListener('touchmove', onDragMove, { passive: false });
  $('screen').addEventListener('touchend', onDragEnd);
  $('screen').addEventListener('touchcancel', onDragEnd);
  // Rotating the phone changes the sheet's height, and every detent is a
  // fraction of it. Without this the sheet keeps yesterday's offset and sits
  // at no detent at all.
  window.addEventListener('resize', () => { if (current) goDetent(detent); });
  $('btn-refresh').addEventListener('click', () => load(state.place));

  // One delegated listener on the screen shell, which never gets replaced --
  // everything inside it is rebuilt on every render.
  $('screen').addEventListener('click', (e) => {
    if (e.target.closest('[data-act="geo"]')) { useGeolocation(); return; }
    const src = e.target.closest('.src');
    if (src) {
      if (src.disabled) return;
      chooseSource(src.dataset.src);
      // `render`, not just a redraw of this screen: it ends by refreshing
      // whatever screen is open, so one call keeps the detail and the forecast
      // underneath it on the same source. Redrawing only the screen left the
      // page behind it showing the source you had just switched away from,
      // which you would find on the way back.
      render(state.data);
      return;
    }
    const li = e.target.closest('li');
    if (!li) return;
    if (li.dataset.find !== undefined) {
      const p = found[+li.dataset.find];
      if (p) load({ slug: p.slug, name: p.name, lat: p.lat, lon: p.lon, adhoc: true });
    } else if (li.dataset.slug) {
      load({ slug: li.dataset.slug, adhoc: false });
    } else { return; }
    lastQuery = '';
    found = [];
    pop();
  });

  $('screen').addEventListener('input', (e) => {
    if (e.target.id !== 'q') return;
    clearTimeout(searchTimer);
    const v = e.target.value;
    searchTimer = setTimeout(() => doSearch(v), 260);
  });

  // The strip is rebuilt with the hero on every render, so the listener lives
  // on a container that never gets replaced.
  $('content').addEventListener('click', (e) => {
    const act = e.target.closest('[data-act]');
    if (act) { (act.dataset.act === 'a2hs' ? a2hsGo : a2hsNo)(); return; }
    const day = e.target.closest('[data-day]');
    if (day) { push('day', day.dataset.day); return; }
    const b = e.target.closest('.src');
    if (!b || b.disabled) return;
    chooseSource(b.dataset.src);
    render(state.data);          // already in the payload: no refetch
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && current) pop();
  });

  // Fresh data enters this app when you open it. So: refetch on every return
  // to the foreground, because that is the only moment we get.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') load(state.place);
  });

  // Keep the "обновлено N мин назад" line honest while the app sits open.
  setInterval(() => {
    if (state.data) $('stamp').textContent = ago(state.data.fetched_at);
  }, 30000);

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register(BASE + 'sw.js', { scope: BASE }).catch(() => {});
  }
  // Home-screen web apps are exempt from the 7-day ITP storage cap, so this
  // makes the cached forecast effectively permanent.
  if (navigator.storage && navigator.storage.persist) {
    navigator.storage.persist().catch(() => {});
  }
  // Quiet enough to ignore, present enough to answer "is my change live?"
  // without opening a terminal.
  if (window.YW_BUILD && window.YW_BUILD !== 'dev') {
    const b = document.createElement('div');
    b.className = 'build';
    b.textContent = window.YW_BUILD;
    // Tapping it loads the diagnostic. Deliberately the least discoverable
    // control in the app and deliberately not behind a URL: a home-screen web
    // app has one fixed `start_url` and no address bar to type into.
    //
    // Fetched rather than bundled, because it is the one feature here that is
    // allowed to need the network -- it exists to be run while someone is
    // looking at the phone. That keeps it out of the cold-load budget
    // entirely. See `static/debug.js`.
    b.addEventListener('click', () => {
      if ($('dbg') || document.getElementById('dbg-js')) return;
      const s = document.createElement('script');
      s.id = 'dbg-js';
      s.src = BASE + 'debug.js';
      s.onload = () => s.remove();
      document.head.appendChild(s);
    });
    document.querySelector('.foot').after(b);
  }
}

document.addEventListener('DOMContentLoaded', boot);
