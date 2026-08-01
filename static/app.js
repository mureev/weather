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

const LS = { place: 'yw.place', payload: 'yw.payload', source: 'yw.source' };

// `source` is the user's *preference*, remembered across cities and launches.
// It is not necessarily what is on screen: if the preferred source has no data
// for the city you just picked, we show one that does and leave the preference
// alone, so going back to a city it covers restores your choice.
let state = { place: null, data: null, busy: false, source: null };

/* ------------------------------------------------------------------ utils */

const fmtT = (v) => (v === null || v === undefined) ? '—' :
  (v > 0 ? '+' : v < 0 ? '−' : '') + Math.round(Math.abs(v)) + '°';

const icon = (key, cls) =>
  `<svg class="${cls || ''}" aria-hidden="true"><use href="#i-${key || 'unknown'}"></use></svg>`;

const DOW = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
const MON = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен',
             'окт', 'ноя', 'дек'];

function dayLabel(iso, i) {
  const d = new Date(iso + 'T12:00:00');
  if (i === 0) return { a: 'Сегодня', b: `${d.getDate()} ${MON[d.getMonth()]}` };
  if (i === 1) return { a: 'Завтра', b: `${d.getDate()} ${MON[d.getMonth()]}` };
  return { a: DOW[d.getDay()], b: `${d.getDate()} ${MON[d.getMonth()]}` };
}

function ago(iso) {
  const t = new Date(iso).getTime();
  if (!isFinite(t)) return '';
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  const hhmm = new Date(t).toLocaleTimeString('ru-RU',
    { hour: '2-digit', minute: '2-digit' });
  if (m < 1) return `обновлено в ${hhmm}`;
  if (m < 60) return `${m} мин назад · ${hhmm}`;
  return `${Math.round(m / 60)} ч назад · ${hhmm}`;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

const num = (v) => (Math.round(v * 10) / 10).toString().replace('.', ',');
const shortTime = (t) => (t || '').includes('T') ? t.slice(11, 16) : (t || '');
const SHORT_DIR = { 'северный': 'С', 'северо-восточный': 'СВ', 'восточный': 'В',
  'юго-восточный': 'ЮВ', 'южный': 'Ю', 'юго-западный': 'ЮЗ',
  'западный': 'З', 'северо-западный': 'СЗ', 'штиль': 'штиль' };
const shortDir = (d) => SHORT_DIR[d] || d || '';

/* ---- the sky ---------------------------------------------------------------
 * The hero sits on this rather than in a card. A box with four lines in it
 * reads as empty; the same four lines on a sky read as calm. Costs no extra
 * data, which was the constraint.
 *
 * Redrawn only when the condition class actually changes -- a star field
 * rebuilt on every 10-minute refresh would flicker for no reason.
 */
const SKY_OF = {
  'clear': 'clear-day', 'clear-night': 'clear-night',
  'partly': 'cloudy-day', 'partly-night': 'cloudy-night',
  'cloudy': 'cloudy-day', 'overcast': 'overcast', 'fog': 'overcast',
  'drizzle': 'rain', 'rain-light': 'rain', 'rain': 'rain',
  'rain-heavy': 'rain', 'thunder': 'rain', 'hail': 'rain',
  'snow-light': 'snow', 'snow': 'snow', 'snow-heavy': 'snow', 'sleet': 'snow',
};
let skyNow = null;
let lastIcon = null;

function setSky(iconKey) {
  lastIcon = iconKey;
  const kind = SKY_OF[iconKey] || 'cloudy-night';
  if (kind === skyNow) return;
  skyNow = kind;
  document.documentElement.dataset.sky = kind;   // on the root: <html> paints the canvas

  // Keep the status bar, the app-switcher card and the notch fill matching the
  // top of the gradient. One source of truth: whatever CSS resolved --sky1 to.
  setThemeColor(getComputedStyle(document.documentElement)
    .getPropertyValue('--sky1').trim());

  let inner = '';
  if (kind === 'clear-night') {
    // Deterministic placement: a star field that jumps around between renders
    // is worse than no star field.
    let stars = '';
    for (let i = 0; i < 60; i++) {
      const x = ((i * 37.7) % 100).toFixed(2);
      const y = ((i * 61.3) % 62).toFixed(2);
      const r = (0.5 + ((i * 13) % 7) / 9).toFixed(2);
      const d = ((i * 7) % 40) / 10;
      stars += `<circle cx="${x}%" cy="${y}%" r="${r}" fill="#fff"
        style="animation-delay:${d}s"/>`;
    }
    inner = `<svg class="stars" width="100%" height="100%">${stars}</svg>`;
  } else if (kind === 'rain') {
    inner = '<div class="drift"></div><div class="fall rain"></div>';
  } else if (kind === 'snow') {
    inner = '<div class="drift"></div><div class="fall snow"></div>';
  } else if (kind !== 'clear-day') {
    inner = '<div class="drift"></div>';
  }
  $('sky').innerHTML = inner;
}

/* --------------------------------------------------------------- rendering */

function pickSource(d) {
  const order = window.YW_SOURCES || ['yandex', 'gismeteo', 'openmeteo'];
  const has = (k) => d.sources && d.sources[k] && d.sources[k].available;
  if (state.source && has(state.source)) return state.source;
  if (d.selected && has(d.selected)) return d.selected;
  return order.find(has) || null;
}

function sourceStrip(d, active) {
  const order = window.YW_SOURCES || ['yandex', 'gismeteo', 'openmeteo'];
  const tabs = order.map((k) => {
    const s = (d.sources || {})[k];
    if (!s) return '';
    // The temperature on each tab is the whole point of having three: you see
    // the disagreement without switching, and judge it yourself. An
    // unavailable source keeps its seat, greyed, with the short reason -- a
    // tab that vanishes teaches you nothing.
    const val = s.available && s.current && s.current.temp_c != null
      ? fmtT(s.current.temp_c) : (s.reason || 'нет данных');
    return `<button class="src ${k === active ? 'sel' : ''}" data-src="${esc(k)}"
      role="tab" aria-selected="${k === active}" ${s.available ? '' : 'disabled'}
      title="${esc(s.reason || '')}">${esc(s.label)}<b>${esc(val)}</b></button>`;
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

function hourlyBlock(hours, nowcast) {
  const summary = nowcast
    ? `<div class="nowcast">${icon('umbrella')}<span>${esc(nowcast)}</span></div>` : '';
  const list = (hours || []).slice(0, 24).filter((h) => h.temp_c != null);
  if (list.length < 2) {
    return summary ? `<div class="card">${summary.replace(/border-bottom[^"]*/, '')}</div>` : '';
  }

  // Column width comes from the stylesheet (--hour-w) rather than being
  // restated here. The two disagreed once -- 58px there, 54px here -- and the
  // symptom was not what a wrong constant usually looks like: the curve
  // drifted 4px left per column and simply stopped short of the last labels.
  const W = hourWidth(), TOP = 24, BOT = 64, H = 72;
  const temps = list.map((h) => h.temp_c);
  const min = Math.min(...temps), max = Math.max(...temps);
  const span = (max - min) || 1;
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
           ends of the curve. -->
      <linearGradient id="tgrad" gradientUnits="userSpaceOnUse"
                      x1="0" y1="${TOP}" x2="0" y2="${BOT}">
        <stop offset="0" stop-color="#ff9f5a"/><stop offset="1" stop-color="#5ec8ff"/>
      </linearGradient>
      <linearGradient id="tfill" gradientUnits="userSpaceOnUse"
                      x1="0" y1="${TOP}" x2="0" y2="${H}">
        <stop offset="0" stop-color="#71a9ff" stop-opacity=".22"/>
        <stop offset="1" stop-color="#71a9ff" stop-opacity="0"/>
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
  const cols = list.map((h, i) => {
    const isNow = nowHour !== null && hourOf(h.time) === nowHour;
    return `<div class="hour${isNow ? ' now' : ''}">
      <div class="gz"><span class="hv" style="top:${(y(h.temp_c) - 20).toFixed(1)}px"
        >${fmtT(h.temp_c)}</span></div>
      ${icon(h.icon, 'wi')}
      <div class="hh">${esc(isNow ? 'сейчас' : shortTime(h.time))}</div>
      <div class="hp">${h.precip_mm ? esc(num(h.precip_mm)) : ''}</div>
    </div>`;
  }).join('');

  return `<div class="card">${summary}<h2>По часам</h2>
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

  const lows = list.map((d) => d.temp_min_c).filter((v) => v != null);
  const highs = list.map((d) => d.temp_max_c);
  const wmin = Math.min(...lows, ...highs);
  const wmax = Math.max(...lows, ...highs);
  const span = (wmax - wmin) || 1;
  const pct = (t) => ((t - wmin) / span) * 100;

  const rows = list.map((d, i) => {
    const l = d.temp_min_c != null ? pct(d.temp_min_c) : 0;
    const r = pct(d.temp_max_c);
    const dot = (i === 0 && nowTemp != null && nowTemp >= wmin && nowTemp <= wmax)
      ? `<u style="left:${pct(nowTemp).toFixed(1)}%"></u>` : '';
    const lab = dayLabel(d.date, i);
    return `<div class="day">
      <div class="d">${esc(lab.a)}<small>${esc(lab.b)}</small></div>
      ${icon(d.icon, 'wi')}
      <span class="lo">${fmtT(d.temp_min_c)}</span>
      <div class="bar"><i style="left:${l.toFixed(1)}%;width:${Math.max(r - l, 3).toFixed(1)}%"></i>${dot}</div>
      <span class="hi">${fmtT(d.temp_max_c)}</span>
    </div>`;
  }).join('');

  return `<div class="card"><h2>Прогноз на ${list.length} дней</h2>${rows}</div>`;
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
  add('Ветер', c.wind_ms != null
    ? `${num(c.wind_ms)} м/с${c.wind_dir ? `<small>${esc(shortDir(c.wind_dir))}</small>` : ''}`
    : null, true);
  add('Влажность', c.humidity_pct != null ? Math.round(c.humidity_pct) + '%' : null);
  add('Давление', c.pressure_mmhg != null ? Math.round(c.pressure_mmhg) + ' мм' : null);
  if (today) {
    add('Восход', today.sunrise);
    add('Закат', today.sunset);
    add('УФ-индекс', today.uv_index != null ? String(today.uv_index) : null);
    add('Вода', today.water_temp_c != null ? fmtT(today.water_temp_c) : null);
  }
  if (cells.length < 3) return '';
  // Whole rows only. Seven cells in a three-column grid leaves two empty boxes
  // staring at you, and the fix is to drop the least useful cell rather than
  // to invent filler for it.
  const whole = cells.slice(0, Math.floor(cells.length / 3) * 3);
  return `<div class="card"><h2>Подробности</h2>
    <div class="facts">${whole.join('')}</div></div>`;
}

function render(d) {
  if (!d || !d.sources) { renderError(d); return; }
  const active = pickSource(d);
  if (!active) { renderError(d); return; }

  const view = d.sources[active];
  const c = view.current;
  if (!c) { renderError(d); return; }

  const today = (view.daily && view.daily[0]) || null;
  const range = today && today.temp_max_c != null
    ? `<span class="hi">${fmtT(today.temp_max_c)}</span>`
      + ` / <span class="lo">${fmtT(today.temp_min_c)}</span>`
    : '';
  const feels = c.feels_like_c != null && Math.round(c.feels_like_c) !== Math.round(c.temp_c)
    ? `ощущается как ${fmtT(c.feels_like_c)}` : '';

  setSky(c.icon);

  const hero = `<div class="hero">
    <div class="ic">${icon(c.icon)}</div>
    <div class="t">${fmtT(c.temp_c)}</div>
    <div class="cond">${esc(c.condition || '')}</div>
    ${range ? `<div class="sub">${range}</div>` : ''}
    ${feels ? `<div class="feels">${feels}</div>` : ''}
  </div>${sourceStrip(d, active)}`;

  $('content').innerHTML = hero
    + hourlyBlock(view.hourly, view.nowcast)
    + dailyBlock(view.daily, c.temp_c)
    + factsBlock(c, today);
  $('city').textContent = (d.place && d.place.name) || '';
  $('pin').style.display = (state.place && state.place.adhoc) ? '' : 'none';
  renderHealth(d, view);
}

function renderError(d) {
  const w = d && d.health && d.health.warnings ? d.health.warnings : [];
  $('content').innerHTML = `<div class="card err">
    <p>Погоду сейчас получить не удалось.</p>
    ${w.length ? `<p style="font-size:13px">${esc(w[0])}</p>` : ''}
  </div>`;
  if (d) renderHealth(d, null);
}

function renderHealth(d, view) {
  const h = d.health || {};
  const badge = $('badge');
  badge.className = 'badge ' + (h.status || 'ok');
  badge.textContent = { degraded: 'неполные данные', stale: 'устарело',
                        down: 'нет данных' }[h.status] || '';
  $('stamp').textContent = ago(d.fetched_at);

  const notes = $('notes');
  // Global problems, plus anything wrong with the source you are looking at.
  // Deliberately *not* "these sources disagree" -- all three temperatures are
  // on the tabs and you can judge that yourself.
  const msgs = (h.warnings || []).concat((view && view.warnings) || []).slice(0, 4);
  if (msgs.length) {
    notes.className = 'notes show';
    notes.innerHTML = `<b>Что не так</b><ul>` +
      msgs.map((m) => `<li>${esc(m)}</li>`).join('') + `</ul>`;
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

async function load(place, { force = false } = {}) {
  state.place = place || state.place;
  if (state.busy) return;
  state.busy = true;
  try {
    const q = placeQuery(state.place);
    const r = await fetch(`${BASE}api/weather?${q}${force ? '&force=1' : ''}`,
                          { headers: { 'Accept': 'application/json' } });
    const d = await r.json();
    state.data = d;
    // On a cold start we ask for nothing and the server picks the default, so
    // adopt whatever it resolved -- otherwise the sheet has no idea which city
    // is current and shows no tick against any of them.
    if (!state.place && d.place) {
      state.place = { slug: d.place.slug, name: d.place.name,
                      lat: d.place.lat, lon: d.place.lon,
                      adhoc: !!d.place.ad_hoc };
    }
    try {
      localStorage.setItem(LS.payload, JSON.stringify(d));
      localStorage.setItem(LS.place, JSON.stringify(state.place));
    } catch (e) { /* private mode; the SW cache still covers us */ }
    render(d);
  } catch (e) {
    if (!state.data) renderError(null);
  } finally {
    state.busy = false;
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
  if (!navigator.geolocation) { alert('Геолокация недоступна в этом браузере.'); return; }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const lat = +pos.coords.latitude.toFixed(PRECISION);
      const lon = +pos.coords.longitude.toFixed(PRECISION);
      load({ slug: `@${lat},${lon}`, name: '…', lat, lon, adhoc: true });
      closeSheet();
    },
    (err) => {
      alert(err.code === 1
        ? 'Доступ к геолокации запрещён. Разрешите его в настройках Safari.'
        : 'Не удалось определить местоположение.');
    },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 }
  );
}

/* ---- the place sheet -------------------------------------------------------
 * Search, geolocation and the saved cities are all answers to one question --
 * "where" -- so they live in one panel instead of three permanent strips. It
 * costs a tap on a decision made twice a month and gives the whole top of the
 * screen back to the weather.
 */
let searchTimer = null;
let savedCities = [];
let found = [];

const GEO_ICON = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.2"/>'
  + '<circle cx="12" cy="12" r="8"/><path d="M12 1.5V4M12 20v2.5M1.5 12H4M20 12h2.5"/></svg>';
const TICK = '<svg class="tick" viewBox="0 0 24 24"><path d="M4 12.5l5 5L20 6.5"/></svg>';

// iOS Safari ignores overflow:hidden on <body>, so the page kept scrolling
// under the open sheet. Pinning the body is the only reliable fix, and
// position:fixed discards the scroll offset -- so it has to be saved on the way
// in and restored on the way out, or opening the sheet silently teleports you
// back to the top of the forecast.
let lockedAt = 0;

// Blend a colour over the current sky the way the scrim does, so the status
// bar matches the dimmed page instead of staying bright above it.
/* The scrim colour composited over the top of the sky, as a solid hex.
 *
 * The scrim itself and the sky are both CSS; this reads *both* back rather
 * than restating either, because a constant written down in two places is the
 * bug that already cost this file a broken hourly curve. Change --scrim in the
 * stylesheet and this follows.
 *
 * What it is for: <meta name="theme-color">, which is browser chrome no scrim
 * inside the page can reach. Note what this is *not*: iOS 26 Safari ignores
 * theme-color entirely and samples a fixed element's background-color instead
 * (see `.edge` in the stylesheet, and DECISIONS.md 14). This remains correct
 * for the installed PWA, for Android, and for Safari before 26 -- a fallback,
 * not the fix, and it agrees with the CSS exactly because both are the same
 * arithmetic on the same two values.
 */
function cssVar(name) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();
}

function scrimTint() {
  const sky = /^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(cssVar('--sky1'));
  const scrim = /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,/\s]+([\d.]+))?/i
    .exec(cssVar('--scrim'));
  if (!sky || !scrim) return '#0a1020';
  const alpha = scrim[4] === undefined ? 1 : parseFloat(scrim[4]);
  const mix = [1, 2, 3].map((i) => Math.round(
    parseInt(scrim[i], 10) * alpha + parseInt(sky[i], 16) * (1 - alpha)));
  return '#' + mix.map((v) => v.toString(16).padStart(2, '0')).join('');
}

function setThemeColor(c) {
  const meta = document.getElementById('theme-color');
  if (meta && c) meta.setAttribute('content', c);
}

function openSheet() {
  lockedAt = window.scrollY;
  // Safari tints the status bar from theme-color, and that strip is browser
  // chrome -- our scrim cannot reach it. Without this the top of the screen
  // stays bright while everything below it dims, which reads as the blur
  // failing to draw.
  setThemeColor(scrimTint());
  document.body.style.top = `-${lockedAt}px`;
  document.body.classList.add('locked');
  $('sheet').classList.add('open');
  renderSheet();
  setTimeout(() => $('q').focus(), 80);
}

function closeSheet() {
  $('sheet').classList.remove('open');
  skyNow = null;                       // force setSky to restore theme-color
  setSky(lastIcon);
  document.body.classList.remove('locked');
  document.body.style.top = '';
  window.scrollTo(0, lockedAt);
  $('q').value = '';
  found = [];
}

function renderSheet() {
  const cur = state.place && state.place.slug;
  const onGps = !!(state.place && state.place.adhoc);
  const out = [];

  // An action, not a list item -- so it gets no container. Boxed, it echoed
  // the search field sitting right above it.
  out.push(`<button class="geolink" data-act="geo">${GEO_ICON}
    <span>Моё местоположение</span>
    ${onGps ? '<span class="on">включено</span>' : ''}</button>`);

  const searching = $('q').value.trim().length >= 2;
  if (searching) {
    out.push('<h3>Найдено</h3>');
    if (!found.length) {
      out.push('<div class="empty">Ничего не найдено</div>');
    } else {
      out.push('<ul class="group">' + found.map((p, i) =>
        `<li data-find="${i}"><span class="nm">${esc(p.name)}</span>
          <span class="sub">${esc(p.subtitle || '')}</span></li>`).join('')
        + '</ul>');
    }
  } else {
    out.push('<h3>Города</h3><ul class="group">' + savedCities.map((c) =>
      `<li data-slug="${esc(c.slug)}" class="${c.slug === cur && !onGps ? 'sel' : ''}">
        <span class="nm">${esc(c.name)}</span>
        ${c.slug === cur && !onGps ? TICK : ''}</li>`).join('') + '</ul>');
  }
  $('plist').innerHTML = out.join('');
}

async function doSearch(q) {
  if (q.trim().length < 2) { found = []; renderSheet(); return; }
  found = [];
  try {
    const r = await fetch(`${BASE}api/search?q=${encodeURIComponent(q)}`);
    found = (await r.json()).results || [];
    renderSheet();
  } catch (e) { /* offline: leave the last results up */ }
}

async function loadCities() {
  try {
    const r = await fetch(`${BASE}api/cities`);
    savedCities = (await r.json()).cities || [];
  } catch (e) { /* ignore */ }
}

/* ------------------------------------------------------------------- boot */

function boot() {
  // Paint whatever we had last, immediately, before any network happens.
  try {
    const cached = localStorage.getItem(LS.payload);
    const place = localStorage.getItem(LS.place);
    if (place) state.place = JSON.parse(place);
    state.source = localStorage.getItem(LS.source) || null;
    if (cached) { state.data = JSON.parse(cached); render(state.data); }
  } catch (e) { /* ignore */ }

  loadCities();
  load(state.place, { force: false });

  $('btn-place').addEventListener('click', openSheet);
  $('btn-refresh').addEventListener('click', () => load(state.place, { force: true }));

  $('sheet').addEventListener('click', (e) => {
    if (e.target.hasAttribute('data-close')) { closeSheet(); return; }
    // The geolocation control is a <button>, the places are <li>s.
    if (e.target.closest('[data-act="geo"]')) { useGeolocation(); return; }
    const li = e.target.closest('li');
    if (!li) return;
    if (li.dataset.find !== undefined) {
      const p = found[+li.dataset.find];
      if (p) load({ slug: p.slug, name: p.name, lat: p.lat, lon: p.lon, adhoc: true });
    } else if (li.dataset.slug) {
      load({ slug: li.dataset.slug, adhoc: false });
    } else { return; }
    closeSheet();
  });

  $('q').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    const v = e.target.value;
    searchTimer = setTimeout(() => doSearch(v), 260);
  });

  // The strip is rebuilt with the hero on every render, so the listener lives
  // on a container that never gets replaced.
  $('content').addEventListener('click', (e) => {
    const b = e.target.closest('.src');
    if (!b || b.disabled) return;
    state.source = b.dataset.src;
    try { localStorage.setItem(LS.source, state.source); } catch (err) {}
    render(state.data);          // already in the payload: no refetch
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && $('sheet').classList.contains('open')) closeSheet();
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
  if (window.navigator.standalone) $('install').classList.add('hide');

  // Quiet enough to ignore, present enough to answer "is my change live?"
  // without opening a terminal.
  if (window.YW_BUILD && window.YW_BUILD !== 'dev') {
    const b = document.createElement('div');
    b.className = 'build';
    b.textContent = window.YW_BUILD;
    $('install').after(b);
  }
}

document.addEventListener('DOMContentLoaded', boot);
