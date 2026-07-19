/*
 * StartupET — vanilla GSAP animation layer.
 *
 * This is a faithful re-implementation of the Azurio template's animation
 * system, reverse-engineered 1:1 from the original compiled bundle so the
 * static Astro build looks and moves identically — but with zero React and
 * zero hydration. Every tween below matches the values the original used
 * (eases, durations, staggers, ScrollTrigger start/end points).
 *
 * Markup drives behavior through data-attributes and classes:
 *   [data-anim="splitLinesLoad"]  hero-style line reveal on page load
 *   [data-anim="splitLines"]      line reveal on scroll-in
 *   [data-anim="animChars"]       char reveal on scroll-in
 *   [data-anim="revealType"]      word blur-in on scrub
 *   [data-anim="inUp"|"fadeIn"]   element fade/slide on scroll-in
 *   .marquee--gsap                infinite horizontal ticker
 *   .pinned-section               stacked-card pin (shrink + fade)
 *   .animate-card-N               staggered batch reveal of a grid
 *   .mxd-scramble                 scramble-in text
 */
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { SplitText } from 'gsap/SplitText';
import { CustomEase } from 'gsap/CustomEase';
import Lenis from 'lenis';

gsap.registerPlugin(ScrollTrigger, SplitText, CustomEase);

// Exact eases from the original bundle.
CustomEase.create('hop', '.87, 0, .13, 1');
CustomEase.create('common', '.23, .65, .74, 1.09');
CustomEase.create('custom', '.23, .65, .74, 1.09');

const prefersReduced =
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ---- 1. Lenis smooth scroll, driven by GSAP's ticker ---- */
let lenisInstance = null;
function initSmoothScroll() {
  if (prefersReduced) return null;
  lenisInstance = new Lenis({ lerp: 0.1, smoothWheel: true, wheelMultiplier: 1 });
  lenisInstance.on('scroll', ScrollTrigger.update);
  gsap.ticker.add((time) => lenisInstance.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);
  return lenisInstance;
}

/* ---- 2. Split-text reveals (lines / chars / word blur) ---- */
function initSplitText() {
  const run = () => {
    document.querySelectorAll('[data-anim]').forEach((el) => {
      const type = el.dataset.anim;
      if (el.dataset.animInit) return;

      if (type === 'splitLinesLoad' || type === 'splitLines' || type === 'splitLinesReverse') {
        SplitText.create(el, {
          type: 'words, lines',
          linesClass: 'line',
          autoSplit: true,
          mask: 'lines',
          aria: 'none',
          onSplit: (self) => {
            if (prefersReduced) return;
            if (type === 'splitLinesLoad') {
              return gsap.from(self.lines, {
                yPercent: 100, rotation: 1, duration: 0.6, stagger: { amount: 0.2 },
              });
            }
            return gsap
              .timeline({
                scrollTrigger: {
                  trigger: el, start: 'top bottom', end: 'top 90%',
                  toggleActions: 'none play none reset',
                },
              })
              .from(self.lines, {
                yPercent: type === 'splitLines' ? 100 : -100,
                rotation: 1, duration: 0.5,
                stagger: { amount: type === 'splitLines' ? 0.2 : 0.1 },
              });
          },
        });
      } else if (type === 'animChars' || type === 'animCharsLoad') {
        SplitText.create(el, {
          type: 'chars, words', charsClass: 'char', mask: 'chars',
          smartWrap: true, aria: 'none',
          onSplit: (self) => {
            if (prefersReduced) return;
            if (type === 'animCharsLoad') {
              return gsap.from(self.chars, {
                yPercent: 100, autoAlpha: 0, duration: 0.6, ease: 'custom',
                stagger: { amount: 0.3 },
              });
            }
            return gsap
              .timeline({
                scrollTrigger: {
                  trigger: el, start: 'top bottom', end: 'top 80%',
                  toggleActions: 'none play none reset',
                },
              })
              .from(self.chars, {
                yPercent: 100, autoAlpha: 0, duration: 0.6, ease: 'custom',
                stagger: { amount: 0.3 },
              });
          },
        });
      } else if (type === 'revealType') {
        const split = SplitText.create(el, { type: 'words', wordsClass: 'word', aria: 'none' });
        if (!prefersReduced) {
          gsap.fromTo(
            split.words,
            { opacity: 0.15, filter: 'blur(4px)', xPercent: 12 },
            {
              opacity: 1, filter: 'blur(0px)', xPercent: 0, stagger: 0.03, ease: 'none',
              scrollTrigger: { trigger: el, start: 'top bottom', end: 'top 60%', scrub: 1.4 },
            }
          );
        }
      }
      el.dataset.animInit = '1';
    });
  };
  if ('fonts' in document) document.fonts.ready.then(run);
  else run();
}

/* ---- 3. Element scroll animations (inUp / fadeIn / clipImage) ---- */
function initElementAnims() {
  if (prefersReduced) return;
  document.querySelectorAll('[data-el-anim]').forEach((el) => {
    const type = el.dataset.elAnim;
    if (type === 'inUp') {
      gsap.fromTo(el, { opacity: 0, y: 50 },
        { opacity: 1, y: 0, ease: 'sine.out',
          scrollTrigger: { trigger: el, toggleActions: 'play none none reverse' } });
    } else if (type === 'fadeIn') {
      gsap.fromTo(el, { opacity: 0 }, { opacity: 1, duration: 2, ease: 'none',
        scrollTrigger: { trigger: el, toggleActions: 'play none none reverse' } });
    } else if (type === 'clipImage') {
      const img = el.querySelector('img');
      gsap.set(el, { clipPath: 'inset(0% 100% 1% 0%)' });
      if (img) gsap.set(img, { scale: 1.2 });
      const tl = gsap.timeline({
        scrollTrigger: { trigger: el, start: 'top bottom', end: 'top 50%', scrub: true },
      });
      tl.to(el, { clipPath: 'inset(0% 0% 0% 0%)' }, '<');
      if (img) tl.to(img, { scale: 1 }, '<');
    }
  });
}

/* ---- 4. Batch card grids (.animate-card-N) ---- */
function initCardBatches() {
  if (prefersReduced) return;
  [2, 3, 4].forEach((n) => {
    const sel = `.animate-card-${n}`;
    if (!document.querySelector(sel)) return;
    gsap.set(sel, { y: 50, opacity: 0 });
    ScrollTrigger.batch(sel, {
      interval: 0.1, batchMax: n,
      onEnter: (b) => gsap.to(b, { opacity: 1, y: 0, ease: 'sine.out', stagger: { each: 0.15 }, overwrite: true }),
      onLeaveBack: (b) => gsap.set(b, { opacity: 0, y: 50, overwrite: true }),
    });
  });
}

/* ---- 5. Infinite marquee ticker ---- */
function initMarquees() {
  document.querySelectorAll('.marquee--gsap').forEach((marquee) => {
    const track = marquee.querySelector('.marquee__top') || marquee.firstElementChild;
    if (!track) return;
    const items = Array.from(track.children);
    if (!items.length) return;
    // duplicate items until the track is at least 2x viewport for a seamless loop
    const original = items.map((i) => i.cloneNode(true));
    while (track.scrollWidth < window.innerWidth * 2) {
      original.forEach((n) => track.appendChild(n.cloneNode(true)));
      if (track.children.length > 200) break;
    }
    if (prefersReduced) return;
    const half = track.scrollWidth / 2;
    gsap.to(track, {
      x: -half, ease: 'none', duration: half / 60,
      repeat: -1, modifiers: { x: gsap.utils.unitize((x) => parseFloat(x) % half) },
    });
  });
}

/* ---- 6. Stacked cards (Journey) ---- */
// CSS makes each card `position: sticky`, so cards naturally pile up as you
// scroll. GSAP scrubs a scale-down + fade on each card as the next one slides
// over it — reproducing the template's recede-and-stack effect without pinning.
function initPinnedStacks() {
  if (prefersReduced) return;
  const mm = gsap.matchMedia();
  mm.add('(min-width: 1200px)', () => {
    const sections = gsap.utils.toArray('.pinned-section');
    sections.forEach((section, i) => {
      if (i === sections.length - 1) return; // last card stays put
      const inner = section.querySelector('.pinned-section__inner') || section.firstElementChild;
      if (!inner) return;
      gsap.to(inner, {
        scale: 0.94, autoAlpha: 0.35, ease: 'none',
        scrollTrigger: { trigger: section, start: 'top top', end: 'bottom top', scrub: true },
      });
    });
  });
}

/* ---- 7. Scramble-in text ---- */
const GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/#*';
function scramble(el) {
  const finalText = el.dataset.final;
  const dur = 500;
  const start = performance.now();
  const step = (now) => {
    const p = Math.min((now - start) / dur, 1);
    const reveal = Math.floor(p * finalText.length);
    let out = '';
    for (let i = 0; i < finalText.length; i++) {
      out += i < reveal || finalText[i] === ' '
        ? finalText[i]
        : GLYPHS[(Math.random() * GLYPHS.length) | 0];
    }
    el.textContent = out;
    if (p < 1) requestAnimationFrame(step);
    else el.textContent = finalText;
  };
  requestAnimationFrame(step);
}
function initScramble() {
  document.querySelectorAll('.mxd-scramble').forEach((el) => {
    const text = el.textContent.trim();
    if (!text) return;
    el.dataset.final = text;
    if (prefersReduced) return;
    ScrollTrigger.create({
      trigger: el, start: 'top 92%', once: true, onEnter: () => scramble(el),
    });
  });
}

/* ---- 8. Custom cursor + trail ---- */
function initCursor() {
  const cursor = document.getElementById('mxd-cursor');
  if (!cursor || prefersReduced || window.matchMedia('(hover: none)').matches) return;
  const dot = cursor.querySelector('.mxd-cursor__dot');
  const pos = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
  const mouse = { ...pos };
  window.addEventListener('mousemove', (e) => { mouse.x = e.clientX; mouse.y = e.clientY; });
  gsap.ticker.add(() => {
    pos.x += (mouse.x - pos.x) * 0.2;
    pos.y += (mouse.y - pos.y) * 0.2;
    if (dot) gsap.set(dot, { x: pos.x, y: pos.y });
  });
  document.querySelectorAll('[data-cursor-text]').forEach((el) => {
    el.addEventListener('mouseenter', () => cursor.classList.add('is-active'));
    el.addEventListener('mouseleave', () => cursor.classList.remove('is-active'));
  });
}

/* ---- 9. Mega-menu overlay (clip-path reveal + staggered lines) ---- */
// Reverse-engineered from the template: overlay clip-path polygon from
// top-collapsed to full (ease "hop"), backdrop blur/tint fades in, the media
// panel scales 1.4 -> 1, and the nav/info line-masks stagger up from -114%.
function initMenu() {
  const menu = document.querySelector('.mxd-menu');
  const hamburger = document.querySelector('.mxd-menu__hamburger');
  if (!menu || !hamburger) return;
  const overlay = menu.querySelector('.mxd-menu__overlay');
  const backdrop = menu.querySelector('.mxd-menu__backdrop');
  const content = menu.querySelector('.mxd-menu__content');
  const media = menu.querySelector('.menu-media__wrapper');
  const lines = menu.querySelectorAll('.menu-line');
  const CLOSED = 'polygon(0% 0%, 100% 0%, 100% 0%, 0% 0%)';
  const OPEN = 'polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)';

  gsap.set(overlay, { clipPath: CLOSED });
  gsap.set(backdrop, { background: 'rgba(var(--base-rgb), 0)', backdropFilter: 'blur(0px)' });
  gsap.set(content, { yPercent: -6 });
  gsap.set(lines, { yPercent: -115 });
  if (media) gsap.set(media, { scale: 1.4 });

  let open = false, tl = null;
  const openMenu = () => {
    if (open) return; open = true;
    menu.style.pointerEvents = 'auto';
    hamburger.classList.add('active');
    lenisInstance && lenisInstance.stop();
    tl && tl.kill();
    tl = gsap.timeline();
    tl.to(overlay, { clipPath: OPEN, duration: 1, ease: 'hop' })
      .to(backdrop, { background: 'rgba(var(--base-rgb), 0.6)', backdropFilter: 'blur(6px)', duration: 1, ease: 'power2.out' }, '<')
      .to(content, { yPercent: 0, duration: 1, ease: 'hop' }, '<')
      .to(media || {}, { scale: 1, duration: 1.2, ease: 'hop' }, '<')
      .to(lines, { yPercent: 0, duration: 0.6, stagger: 0.04, ease: 'hop' }, '<0.25');
  };
  const closeMenu = () => {
    if (!open) return; open = false;
    hamburger.classList.remove('active');
    tl && tl.kill();
    tl = gsap.timeline({ onComplete: () => { menu.style.pointerEvents = 'none'; lenisInstance && lenisInstance.start(); } });
    tl.to(lines, { yPercent: -115, duration: 0.3, ease: 'power2.in' })
      .to(content, { yPercent: -6, duration: 0.8, ease: 'hop' }, '<')
      .to(backdrop, { background: 'rgba(var(--base-rgb), 0)', backdropFilter: 'blur(0px)', duration: 0.8, ease: 'power2.in' }, '<')
      .to(overlay, { clipPath: CLOSED, duration: 0.8, ease: 'hop' }, '<0.1')
      .set(media || {}, { scale: 1.4 });
  };

  hamburger.addEventListener('click', (e) => { e.preventDefault(); open ? closeMenu() : openMenu(); });
  backdrop.addEventListener('click', closeMenu);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); });
  menu.querySelectorAll('a[href^="#"]').forEach((a) => a.addEventListener('click', closeMenu));
}

/* ---- 10. Light / dark theme toggle ---- */
function initThemeToggle() {
  const KEY = 'startupet-theme';
  const btn = document.getElementById('color-switcher');
  const root = document.documentElement;
  const apply = (theme) => {
    root.setAttribute('color-scheme', theme);
    if (btn) {
      btn.setAttribute('aria-checked', theme === 'dark' ? 'true' : 'false');
      const label = btn.querySelector('.switcher-text');
      if (label) label.textContent = theme === 'dark' ? 'Day' : 'Night';
    }
  };
  let current = root.getAttribute('color-scheme') || 'light';
  try { current = localStorage.getItem(KEY) || current; } catch {}
  apply(current);
  btn && btn.addEventListener('click', () => {
    const next = root.getAttribute('color-scheme') === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(KEY, next); } catch {}
    apply(next);
  });
}

/* ---- 11. Intro page-transition wipe (signature reveal on load) ---- */
function initIntro() {
  const panel = document.getElementById('mxd-page-transition-panel') ||
    document.querySelector('.mxd-page-transition');
  if (!panel || prefersReduced) return;
  gsap.fromTo(panel, { yPercent: 0 }, { yPercent: -100, duration: 0.8, ease: 'hop', delay: 0.05 });
}

export function initAnimations() {
  if (typeof window === 'undefined') return;
  initThemeToggle();
  initMenu();
  initIntro();
  initSmoothScroll();
  initSplitText();
  initElementAnims();
  initCardBatches();
  initMarquees();
  initPinnedStacks();
  initScramble();
  initCursor();
  // settle triggers once everything (fonts, images) is in
  window.addEventListener('load', () => ScrollTrigger.refresh());
  setTimeout(() => ScrollTrigger.refresh(), 400);
}
