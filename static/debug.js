/* CM Weather -- the one-shot diagnostic. Loaded on demand, never in the shell.
 *
 * This exists because of a specific failure: a layout bug that only happens on
 * one phone took six deploys, and each deploy asked its owner to look at
 * something and describe it. That loop does not converge. A desktop browser
 * cannot see the defect, and a person cannot be asked to measure a 16ms frame
 * gap by eye.
 *
 * So: tap the build hash, and this runs the whole battery once -- environment,
 * geometry, colours, the close button, and both animations sampled frame by
 * frame -- and prints a verdict per line. One screenshot answers everything a
 * session could otherwise spend four round trips asking.
 *
 * Not part of `SHELL_FILES` and not precached, so it costs a cold load exactly
 * nothing. Fetched over the same origin, so `default-src 'self'` is untouched.
 * The service worker serves it stale-while-revalidate: the first tap after a
 * deploy may run the previous copy, the second runs the new one.
 *
 * The one measurement that matters most is **frame pacing**, not position. A
 * transition can report a perfect `translateY` series while nothing reaches
 * the glass, so what this looks for is gaps: if `requestAnimationFrame` stops
 * being called for 200ms, the main thread is busy and no frame can be painted,
 * whatever the computed style says. That distinguishes "the animation is
 * wrong" from "the animation is right and the phone is too busy to draw it",
 * which are different bugs with different fixes and look identical on video.
 */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const rows = [];
  const OK = 1, BAD = 0, INFO = -1;
  const say = (verdict, label, value) => rows.push([verdict, label, String(value)]);
  const r1 = (n) => Math.round(n * 10) / 10;

  /* env() and the viewport units cannot be read from JS, and a custom
     property's computed value is its token stream rather than a length. Both
     have to be given to a box and measured back off it. */
  function lenOf(css) {
    const p = document.createElement('div');
    p.style.cssText = 'position:fixed;top:0;left:0;width:1px;visibility:hidden;'
      + 'pointer-events:none;height:' + css;
    document.documentElement.appendChild(p);
    const h = p.getBoundingClientRect().height;
    p.remove();
    return Math.round(h);
  }

  const box = (sel) => {
    const el = document.querySelector(sel);
    return el ? el.getBoundingClientRect() : null;
  };
  const rgb = (sel, prop) => {
    const el = sel === ':root' ? document.documentElement
      : document.querySelector(sel);
    return el ? getComputedStyle(el)[prop || 'backgroundColor'] : '-';
  };

  /* ---- who paints the top of the screen -------------------------------
   * Written after two failed attempts at a band across the top of the phone
   * that no render here could reproduce. The rule in CLAUDE.md is that a
   * complaint from the device gets a measurement from the device, and this is
   * the measurement: walk down the first 160 points of the screen and report
   * every place the *owner* of that pixel changes.
   *
   * `elementFromPoint` answers with the topmost hit-testable element, and
   * `pointer-events:none` layers are invisible to it -- `.sky` and `.edge`
   * both are -- so their rectangles are printed separately rather than
   * inferred. Between the two, a band has nowhere to hide: either some element
   * starts or stops at its edge, or the sky's own box does not reach the top.
   */
  function skyBand() {
    say(INFO, '— верх экрана —', '');

    const inset = lenOf('env(safe-area-inset-top)');
    say(INFO, 'safe-area сверху', inset + 'pt');
    say(INFO, 'innerHeight / screen', window.innerHeight + ' / ' + screen.height);

    for (const sel of ['.sky', '.sky .fx', '.edge-top', '.wrap']) {
      const b = box(sel);
      say(b ? INFO : BAD, 'rect ' + sel,
        b ? `top ${r1(b.top)} h ${r1(b.height)}  ${rgb(sel)}` : 'нет элемента');
    }

    // Every effect layer, with the box it actually occupies and its opacity --
    // a layer that stops short of the top is the band, by definition.
    const layers = [...document.querySelectorAll('#fx > *')];
    say(layers.length ? INFO : BAD, 'слоёв неба', layers.length || 'ни одного');
    for (const el of layers) {
      const b = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      say(INFO, '  ' + (el.getAttribute('class') || el.tagName.toLowerCase()),
        `top ${r1(b.top)} h ${r1(b.height)} op ${r1(parseFloat(cs.opacity))}`);
    }

    // The mask is the thing most likely to be drawing the edge, and it is not
    // visible in any rectangle -- so print it verbatim and let a human read it.
    const fx = document.querySelector('.sky .fx');
    if (fx) {
      const cs = getComputedStyle(fx);
      say(INFO, 'маска .fx', cs.maskImage || cs.webkitMaskImage || 'нет');
    }

    // The walk. Only transitions are printed: a run of identical owners is
    // one line, so this stays short enough to photograph.
    const x = Math.round(window.innerWidth / 2);
    let last = null, runFrom = 0;
    const seen = [];
    for (let y = 0; y <= 160; y += 2) {
      const el = document.elementFromPoint(x, y);
      const id = el ? (el.id ? '#' + el.id
        : (el.getAttribute('class') || el.tagName).split(' ')[0]) : 'null';
      if (id !== last) {
        if (last !== null) seen.push(`${runFrom}-${y - 2}: ${last}`);
        last = id; runFrom = y;
      }
    }
    seen.push(`${runFrom}-160: ${last}`);
    say(INFO, 'кто сверху (x=центр)', seen.join('   '));
    say(seen.length <= 2 ? OK : INFO, 'смен владельца', seen.length - 1);
  }

  /* ---- the instrumented run ---------------------------------------------
   * Samples every animation frame for `ms`, recording the sheet's actual
   * translateY and whether it is visible. `performance.now()` deltas between
   * consecutive callbacks are the interesting part: a browser that is
   * reflowing cannot call this, so a gap here is a gap on screen.
   */
  function watch(ms) {
    return new Promise((done) => {
      const el = $('screen');
      const s = [];
      const t0 = performance.now();
      // One live declaration, resolved once per frame rather than twice.
      //
      // This is the observer effect, and it is large enough to matter: reading
      // a computed style forces a style recalculation, so an instrument that
      // reads two of them per frame reports the animation as jankier than it
      // is. The first version did exactly that and blamed the phone. Every
      // frame here costs one recalc, and `pacing` reports what that costs.
      const cs = getComputedStyle(el);
      const tick = () => {
        const now = performance.now() - t0;
        let y = NaN;
        try { y = new DOMMatrixReadOnly(cs.transform).m42; } catch (e) { /* */ }
        s.push([now, y, cs.visibility === 'visible' ? 1 : 0]);
        if (now < ms) requestAnimationFrame(tick);
        else done(s);
      };
      requestAnimationFrame(tick);
    });
  }

  function pacing(name, s, expectFrom, expectTo) {
    if (!s.length) { say(BAD, name, 'кадров не записано'); return; }
    let maxGap = 0, slow = 0;
    for (let i = 1; i < s.length; i++) {
      const g = s[i][0] - s[i - 1][0];
      if (g > maxGap) maxGap = g;
      if (g > 20) slow++;
    }
    const first = s[0], last = s[s.length - 1];
    const moved = s.filter((f) => f[2] === 1);
    say(INFO, name + ': кадров', s.length + ' за ' + Math.round(last[0]) + 'ms');
    say(maxGap < 40 ? OK : BAD, name + ': макс. пауза',
      Math.round(maxGap) + 'ms' + (maxGap < 40 ? '' : '  ← главный поток занят'));
    say(slow <= 2 ? OK : BAD, name + ': кадров >20ms', slow);
    say(INFO, name + ': translateY',
      r1(first[1]) + ' → ' + r1(last[1]));
    if (moved.length) {
      say(Math.abs(moved[0][1] - expectFrom) < 40 ? OK : BAD,
        name + ': первый видимый Y',
        r1(moved[0][1]) + '  (ожидается ' + Math.round(expectFrom) + ')');
    }
    say(Math.abs(last[1] - expectTo) < 12 ? OK : BAD,
      name + ': конечный Y', r1(last[1]) + '  (ожидается ' + Math.round(expectTo) + ')');
  }

  function environment() {
    const vv = window.visualViewport;
    say(INFO, 'сборка', window.YW_BUILD || '-');
    say(INFO, 'standalone', navigator.standalone === true);
    say(INFO, 'экран', screen.width + '×' + screen.height
      + '  dpr ' + window.devicePixelRatio);
    say(INFO, 'inner', window.innerWidth + '×' + window.innerHeight);
    say(INFO, 'visual', vv ? Math.round(vv.width) + '×' + Math.round(vv.height)
      + ' @' + Math.round(vv.offsetTop) : '-');
    say(INFO, 'env t/b', lenOf('env(safe-area-inset-top)') + ' / '
      + lenOf('env(safe-area-inset-bottom)'));
    say(INFO, 'vh/dvh', lenOf('100vh') + ' / ' + lenOf('100dvh'));
    say(INFO, 'svh/lvh', lenOf('100svh') + ' / ' + lenOf('100lvh'));
    say(INFO, 'ниже вьюпорта', (screen.height - window.innerHeight) + 'pt');
    // The canvas paints everything below the viewport; if it disagrees with
    // the sheet there is a permanent band along the bottom of the display.
    const canvas = rgb(':root'), sheet = rgb('#screen');
    say(canvas === sheet ? OK : BAD, 'канва = лист', canvas + '  /  ' + sheet);
    say(rgb('.edge-bot') === canvas ? OK : BAD, 'edge-bot = канва', rgb('.edge-bot'));
  }

  function chrome() {
    const c = box('#screen .close'), g = document.querySelector('#screen .close svg');
    const t = box('#screen-title');
    if (!c || !g || !t) { say(BAD, 'шапка', 'элементы не найдены'); return; }
    // getBBox is the *ink*, not the box: a path that uses the middle of its
    // viewBox draws an icon smaller than its own width, which is how a 15px
    // glyph turned out to be a 7.5pt mark inside a 30pt circle.
    let ink = null;
    try { ink = g.getBBox(); } catch (e) { /* not rendered */ }
    const scale = ink && g.viewBox && g.viewBox.baseVal.width
      ? g.getBoundingClientRect().width / g.viewBox.baseVal.width : 1;
    say(c.width === 30 && c.height === 30 ? OK : BAD, 'круг',
      r1(c.width) + '×' + r1(c.height));
    if (ink) {
      const w = ink.width * scale;
      say(w / c.width > 0.33 && w / c.width < 0.5 ? OK : BAD, 'крестик / круг',
        r1(w) + 'pt = ' + Math.round(w / c.width * 100) + '%  (iOS ≈ 40%)');
    }
    /* Centred on the **header**, grabber and all -- not on the title, and not
     * on the title's first line. Both of those were shipped and both read as
     * off: the header is taller than the title, and its padding is asymmetric
     * because the grabber needs room above.
     *
     * So the three gaps are measured against each other rather than against a
     * number in the stylesheet. Top, bottom and right come out equal or the
     * button is not where it claims to be, whatever `--nav-inset` says. */
    const bar = box('#screen .navbar');
    const gapTop = c.top - bar.top;
    const gapBot = bar.bottom - c.bottom;
    const gapRight = bar.right - c.right;
    say(Math.abs(gapTop - gapBot) < 1.5 ? OK : BAD, 'зазоры верх/низ',
      r1(gapTop) + ' / ' + r1(gapBot));
    say(Math.abs(gapRight - gapTop) < 2 ? OK : BAD, 'зазор справа',
      r1(gapRight) + '  (верт. ' + r1(gapTop) + ')');
    say(INFO, '--nav-inset', lenOf('var(--nav-inset)') + 'pt');
    // Kept as information rather than a verdict: the button is deliberately
    // *not* aligned to the title any more, so a non-zero number here is now
    // expected and only interesting if it is wild.
    const line = parseFloat(getComputedStyle(
      document.querySelector('#screen-title')).lineHeight);
    const firstLineMid = t.top + (isFinite(line) ? line : t.height) / 2;
    say(INFO, 'кнопка vs 1-я строка',
      r1((c.top + c.height / 2) - firstLineMid) + 'pt');
  }

  function geometry(detents) {
    say(INFO, 'детенты (top)', detents.map((d) => Math.round(d)).join('  '));
    const b = box('#screen');
    say(b && b.bottom >= window.innerHeight - 1 ? OK : BAD, 'низ листа',
      b ? r1(b.bottom) + '  (вьюпорт ' + window.innerHeight + ')' : '-');
  }

  function render() {
    const el = document.createElement('div');
    el.id = 'dbg';
    el.style.cssText = 'position:fixed;inset:0;z-index:200;overflow:auto;'
      + 'background:#000;color:#dfe6f5;padding:60px 10px 40px;'
      + 'font:400 10.5px/1.5 ui-monospace,Menlo,monospace;white-space:pre';
    const bad = rows.filter((r) => r[0] === BAD).length;
    const head = (bad ? '✗ ПРОБЛЕМ: ' + bad : '✓ всё в порядке')
      + '   ' + new Date().toLocaleTimeString('ru-RU') + '\n\n';
    el.textContent = head + rows.map(([v, k, val]) =>
      (v === OK ? '✓ ' : v === BAD ? '✗ ' : '  ')
      + (k + '                        ').slice(0, 24) + val).join('\n');
    const close = document.createElement('button');
    close.textContent = 'закрыть';
    close.style.cssText = 'position:fixed;top:60px;right:12px;z-index:201;'
      + 'background:#222c44;color:#dfe6f5;border:0;border-radius:8px;'
      + 'padding:8px 12px;font:600 12px system-ui';
    close.addEventListener('click', () => { el.remove(); close.remove(); });
    document.body.append(el, close);
  }

  /** Frame pacing with **no style reads at all** -- the control.
   *
   *  `watch` resolves a computed style once per frame, which forces a recalc
   *  and makes every animation it measures look worse than it is. This runs
   *  the same number of frames and touches nothing, so the difference between
   *  the two numbers is the instrument's own cost. Without it, a report saying
   *  "26 of 28 frames over 20ms" cannot be read: it might be the app, and it
   *  might be the tape measure.
   */
  function idlePacing(ms) {
    return new Promise((done) => {
      const gaps = [];
      let last = performance.now();
      const t0 = last;
      const tick = () => {
        const now = performance.now();
        gaps.push(now - last);
        last = now;
        if (now - t0 < ms) requestAnimationFrame(tick);
        else done(gaps);
      };
      requestAnimationFrame(tick);
    });
  }

  async function run() {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    environment();

    const idle = await idlePacing(400);
    const idleSlow = idle.filter((g) => g > 20).length;
    say(INFO, 'холостой ход',
      idle.length + ' кадров, >20ms: ' + idleSlow
      + ', макс ' + Math.round(Math.max.apply(null, idle)) + 'ms');

    // A real day, opened the way a finger opens it, so nothing here is a
    // special path that behaves better than the one that ships.
    const row = document.querySelector('.day[data-day]');
    if (!row) { say(BAD, 'запуск', 'нет строки дня'); render(); return; }

    const innerBefore = window.innerHeight;
    const opening = watch(900);
    row.click();
    const openSeries = await opening;

    /* The line this whole investigation turns on.
     *
     * A scroll lock that pins the document -- `body { position: fixed }`, the
     * textbook one -- collapses a standalone iOS web app to the **small**
     * viewport. `innerHeight` drops by the status-bar inset and stays there
     * while the sheet is open, which is where an unpaintable 59pt band along
     * the bottom of the phone came from, and six deploys went looking for it
     * in the stylesheet. Nothing on a desktop can show this: no desktop
     * browser has a small viewport to collapse to.
     *
     * So it is measured *while the sheet is up*, which is the only moment the
     * lock is applied. `lvh` is the display; `innerHeight` must equal it. */
    say(window.innerHeight === innerBefore ? OK : BAD,
      'inner при открытом', window.innerHeight
        + (window.innerHeight === innerBefore ? ''
          : '  ← было ' + innerBefore + ', документ запинен'));
    say(window.innerHeight === lenOf('100lvh') ? OK : BAD,
      'inner = lvh', window.innerHeight + ' / ' + lenOf('100lvh'));

    const h = $('screen').offsetHeight;
    const midCss = parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue('--sheet-mid')) || 38;
    pacing('открытие', openSeries, h, h * midCss / 100);

    geometry([box('#screen') ? box('#screen').top : 0]);
    chrome();
    skyBand();

    await wait(300);
    const closing = watch(900);
    history.back();
    pacing('закрытие', await closing, h * midCss / 100, h);

    await wait(200);
    render();
  }

  run();
})();
