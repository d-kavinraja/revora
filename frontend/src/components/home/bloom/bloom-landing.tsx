'use client';

import { useEffect, useRef } from 'react';
import { gsap } from 'gsap';
import { Observer } from 'gsap/Observer';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Lenis from 'lenis';

import { BloomHero } from './bloom-hero';
import { BloomStats } from './bloom-stats';
import { BloomPreview } from './bloom-preview';
import { BloomModels } from './bloom-models';
import { BloomLoop } from './bloom-loop';
import { BloomCta } from './bloom-cta';
import { BloomFooter } from './bloom-footer';
import { buildGlass, buildPetals, buildSqFields, startGlassFlicker } from './bloom-motion';

import './bloom.css';

/**
 * Bloom landing orchestrator.
 *
 * Owns the intro zoom-out timeline, Lenis smooth scroll, and every
 * ScrollTrigger used by the page. Everything is created inside gsap contexts
 * (and a gsap.matchMedia) so navigating away from `/` reverts pins, tweens,
 * tickers and the scroll lock without leaking into /chat, /dashboard or /admin.
 */
export function BloomLanding() {
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    gsap.registerPlugin(ScrollTrigger, Observer);
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    document.body.classList.add('bloom-page');

    // ── Lenis smooth scroll ────────────────────────────────────────────────
    const lenis = new Lenis({
      duration: 1.25,
      easing: (t: number) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      smoothWheel: true,
    });
    lenis.on('scroll', ScrollTrigger.update);
    const tick = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);

    // Anchor links scroll through Lenis; external + route links untouched.
    const onAnchorClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      const anchor = target?.closest?.('a[href^="#"]');
      if (!anchor) return;
      const href = anchor.getAttribute('href');
      if (!href || href.length < 2) return;
      const section = document.querySelector(href);
      if (!section) return;
      event.preventDefault();
      // Never let the #loop step gate swallow an in-page navigation.
      releaseLoopGate?.();
      lenis.scrollTo(section as HTMLElement, { duration: 1.6, force: true });
    };
    root.addEventListener('click', onAnchorClick);

    // Scroll setup lives in its own context so it can be created either
    // synchronously (reduced motion) or after the intro completes.
    let scrollCtx: ReturnType<typeof gsap.context> | null = null;
    let media: gsap.MatchMedia | null = null;

    // #loop step-gate handles, kept at effect scope so the anchor handler and
    // unmount cleanup can always release the wheel lock.
    let stepObserver: Observer | null = null;
    let settleCall: gsap.core.Tween | null = null;
    let releaseLoopGate: (() => void) | null = null;

    const setupScroll = () => {
      // ── Counters ─────────────────────────────────────────────────────────
      const proxy = { p: 0 };
      const setCounters = (p: number) => {
        root.querySelectorAll<HTMLElement>('.card').forEach((card) => {
          const value = card.querySelector('b');
          if (!value) return;
          const to = parseFloat(card.dataset.to ?? '0');
          const dec = parseInt(card.dataset.dec ?? '0', 10);
          const suf = card.dataset.suf ?? '';
          value.textContent = (to * p).toFixed(dec) + suf;
        });
      };

      // ── Hero parallax ────────────────────────────────────────────────────
      const heroTl = gsap.timeline({
        scrollTrigger: { trigger: '#hero', start: 'top top', end: 'bottom top', scrub: true },
      });
      heroTl.to('#heroTitle', { yPercent: -60, ease: 'none' }, 0);
      root.querySelectorAll<HTMLElement>('#hero [data-par]').forEach((el) => {
        heroTl.to(el, { y: Number(el.dataset.par ?? 0) * 2, ease: 'none' }, 0);
      });
      heroTl.to('.hero-media', { yPercent: 8, ease: 'none' }, 0);

      // ── Generic reveals ──────────────────────────────────────────────────
      gsap.utils.toArray<HTMLElement>('.reveal').forEach((el) => {
        gsap.from(el, {
          opacity: 0,
          y: 16,
          duration: 0.8,
          ease: 'power3.out',
          scrollTrigger: { trigger: el, start: 'top 85%' },
        });
      });

      // ── Word reveals (stats / loop / cta) ────────────────────────────────
      gsap.utils.toArray<HTMLElement>(
        '#stats .split, #preview .split, #models .split, #loop .split, #cta .split',
      ).forEach((el) => {
        gsap.from(el.querySelectorAll('.w'), {
          opacity: 0,
          y: 22,
          filter: 'blur(8px)',
          duration: 0.9,
          stagger: 0.06,
          ease: 'power3.out',
          scrollTrigger: { trigger: el, start: 'top 80%' },
        });
      });

      // ── Showcase card entrances (preview + models) ──────────────────────
      const showcaseGroups = [
        { selector: '#preview .reveal-card', stagger: 0.12 },
        { selector: '#models .model-card', stagger: 0.12 },
      ] as const;
      showcaseGroups.forEach(({ selector, stagger }) => {
        const cards = gsap.utils.toArray<HTMLElement>(selector);
        if (!cards.length) return;
        if (reduceMotion) {
          gsap.set(cards, { clearProps: 'all' });
          return;
        }
        gsap.from(cards, {
          y: 44,
          scale: 0.97,
          opacity: 0,
          filter: 'blur(6px)',
          duration: 0.95,
          stagger,
          ease: 'power3.out',
          // Drop inline styles so equal-height footers keep one baseline.
          clearProps: 'transform,opacity,filter',
          scrollTrigger: {
            trigger: cards[0].closest('section') ?? selector,
            start: 'top 78%',
          },
        });
      });

      if (!reduceMotion) {
        // Inner rows settle just after their cards.
        const rows = gsap.utils.toArray<HTMLElement>(
          '#preview .pipeline-list li, #preview .finding',
        );
        if (rows.length) {
          gsap.from(rows, {
            y: 16,
            opacity: 0,
            duration: 0.65,
            stagger: 0.07,
            ease: 'power3.out',
            clearProps: 'transform,opacity',
            scrollTrigger: { trigger: '#preview', start: 'top 74%' },
          });
        }

        // Scrubbed watercolor parallax, matching the hero and #loop clouds.
        gsap.to('.preview-cloud', {
          x: -55,
          y: 24,
          ease: 'none',
          scrollTrigger: { trigger: '#preview', start: 'top bottom', end: 'bottom top', scrub: 1 },
        });
        gsap.to('.models-cloud', {
          x: 55,
          y: 24,
          ease: 'none',
          scrollTrigger: { trigger: '#models', start: 'top bottom', end: 'bottom top', scrub: 1 },
        });
      }

      // ── Glass flicker (after the intro entrance has settled) ────────────
      if (!reduceMotion) startGlassFlicker(root);

      // ── Responsive scroll behaviors ─────────────────────────────────────
      media = gsap.matchMedia();

      media.add('(min-width: 901px)', () => {
        gsap.from('.card', {
          y: 40,
          opacity: 0,
          duration: 0.8,
          stagger: 0.08,
          ease: 'power3.out',
          scrollTrigger: { trigger: '.cards', start: 'top 70%' },
        });

        // Pinned stats: counters scrub 0→1 while the tree rises behind the
        // cards and the frosted logo band.
        const statsTl = gsap.timeline({
          scrollTrigger: { trigger: '#stats', start: 'top top', end: '+=120%', pin: true, scrub: 1 },
        });
        statsTl
          .to(proxy, { p: 1, ease: 'none', onUpdate: () => setCounters(proxy.p) }, 0)
          .fromTo('#tree', { yPercent: 75 }, { yPercent: 6, ease: 'none' }, 0);
      });

      media.add('(max-width: 900px)', () => {
        gsap.from('.card', {
          y: 30,
          opacity: 0,
          duration: 0.8,
          stagger: 0.08,
          ease: 'power3.out',
          scrollTrigger: { trigger: '.cards', start: 'top 85%' },
        });
        gsap.to(proxy, {
          p: 1,
          duration: 2,
          ease: 'power2.out',
          onUpdate: () => setCounters(proxy.p),
          scrollTrigger: { trigger: '.cards', start: 'top 80%' },
        });
        gsap.fromTo(
          '#tree',
          { yPercent: 40 },
          {
            yPercent: 0,
            ease: 'none',
            scrollTrigger: { trigger: '#stats', start: 'top bottom', end: 'bottom top', scrub: true },
          },
        );
      });

      media.add('(min-width: 761px)', () => {
        // Discrete step gate: one completed transition per scroll gesture.
        const panels = gsap.utils.toArray<HTMLElement>('.panel');
        const gateRef = {
          activeIndex: 0 as 0 | 1 | 2,
          isGateActive: false,
          isTransitioning: false,
          releaseUntil: 0,
        };
        const disposers: Array<() => void> = [];

        const activateIndex = (index: number) => {
          panels.forEach((panel, i) => panel.classList.toggle('is-active', i === index));
        };
        const lockFor = (seconds: number) => {
          gateRef.isTransitioning = true;
          settleCall?.kill();
          settleCall = gsap.delayedCall(seconds, () => {
            gateRef.isTransitioning = false;
          });
        };
        const releaseGate = () => {
          if (!gateRef.isGateActive) return;
          gateRef.isGateActive = false;
          gateRef.isTransitioning = false;
          // Ignore ScrollTrigger callbacks while the programmatic scroll out
          // of the pin is still running, or it would re-engage at step 1.
          gateRef.releaseUntil = performance.now() + 1200;
          settleCall?.kill();
          settleCall = null;
          stepObserver?.disable();
          lenis.start();
        };
        releaseLoopGate = releaseGate;

        const goToStep = (index: number) => {
          gateRef.activeIndex = index as 0 | 1 | 2;
          activateIndex(index);
          lockFor(0.85); // 0.65s panel slide + 0.2s settle buffer
        };
        const step = (direction: 1 | -1) => {
          if (!gateRef.isGateActive || gateRef.isTransitioning) return;
          const next = gateRef.activeIndex + direction;
          if (next >= 0 && next <= 2) {
            goToStep(next);
            return;
          }
          // First/last step is settled — hand scrolling back to Lenis.
          releaseGate();
          lenis.scrollTo(direction > 0 ? '#cta' : '#models', {
            duration: 0.9,
            force: true,
            lock: true,
          });
        };
        const engageGate = (index: 0 | 1 | 2) => {
          if (performance.now() < gateRef.releaseUntil) return;
          gateRef.activeIndex = index;
          gateRef.isGateActive = true;
          activateIndex(index);
          lenis.stop();
          stepObserver?.enable();
          lockFor(0.5); // absorb arrival momentum before the first gesture counts
        };

        if (!reduceMotion) {
          stepObserver = Observer.create({
            target: window,
            type: 'wheel,touch',
            wheelSpeed: -1,
            tolerance: 14,
            preventDefault: true,
            // wheelSpeed: -1 makes a downward wheel/touch gesture fire onUp.
            onUp: () => step(1),
            onDown: () => step(-1),
          });
          stepObserver.disable();

          const pinTrigger = ScrollTrigger.create({
            trigger: '#loop',
            start: 'top top',
            end: '+=100%',
            pin: true,
            anticipatePin: 1,
            onEnter: () => engageGate(0),
            onEnterBack: () => engageGate(2),
          });

          const onKeyDown = (event: KeyboardEvent) => {
            if (!gateRef.isGateActive) return;
            if (event.key === 'ArrowDown' || event.key === 'PageDown') {
              event.preventDefault();
              step(1);
            } else if (event.key === 'ArrowUp' || event.key === 'PageUp') {
              event.preventDefault();
              step(-1);
            }
          };
          window.addEventListener('keydown', onKeyDown);
          disposers.push(
            () => window.removeEventListener('keydown', onKeyDown),
            () => pinTrigger.kill(),
          );
        }

        panels.forEach((panel, index) => {
          const selectThis = () => goToStep(index);
          // Hover only counts before the gate engages; once pinned, click or
          // focus is the deliberate override.
          const hoverThis = () => {
            if (!gateRef.isGateActive) goToStep(index);
          };
          panel.addEventListener('mouseenter', hoverThis);
          panel.addEventListener('focus', selectThis);
          panel.addEventListener('click', selectThis);
          disposers.push(() => {
            panel.removeEventListener('mouseenter', hoverThis);
            panel.removeEventListener('focus', selectThis);
            panel.removeEventListener('click', selectThis);
          });
        });

        gsap.from('.panel-in', {
          y: 120,
          opacity: 0,
          duration: 1.1,
          stagger: 0.12,
          ease: 'power3.out',
          scrollTrigger: { trigger: '#loop', start: 'top 60%' },
        });
        gsap.to('.loop-cloud', {
          x: 60,
          ease: 'none',
          scrollTrigger: { trigger: '#loop', start: 'top bottom', end: 'bottom top', scrub: true },
        });

        return () => {
          releaseGate();
          settleCall?.kill();
          settleCall = null;
          stepObserver?.kill();
          stepObserver = null;
          releaseLoopGate = null;
          disposers.forEach((off) => off());
        };
      });

      media.add('(max-width: 760px)', () => {
        gsap.utils.toArray<HTMLElement>('.panel').forEach((panel) => {
          gsap.from(Array.from(panel.children), {
            y: 28,
            opacity: 0,
            duration: 0.9,
            stagger: 0.1,
            ease: 'power3.out',
            clearProps: 'transform,opacity',
            scrollTrigger: { trigger: panel, start: 'top 85%' },
          });
        });
      });

      // ── CTA ──────────────────────────────────────────────────────────────
      gsap.fromTo(
        '#ctaImg',
        { yPercent: -12 },
        {
          yPercent: 0,
          ease: 'none',
          scrollTrigger: { trigger: '#cta', start: 'top bottom', end: 'bottom bottom', scrub: true },
        },
      );
      gsap.from('#ctaCard', {
        y: 80,
        scale: 0.94,
        opacity: 0,
        filter: 'blur(10px)',
        duration: 1.2,
        ease: 'power3.out',
        scrollTrigger: { trigger: '#cta', start: 'top 60%' },
      });

      // ── Footer emblem: dots bounce → merge → mark draws → ring draws ────
      const dots = gsap.utils.toArray<SVGCircleElement>('.fdot');
      if (dots.length === 3) {
        gsap
          .timeline({ scrollTrigger: { trigger: '#footer', start: 'top 92%' } })
          .to(dots, { y: -8, duration: 0.25, stagger: 0.08, yoyo: true, repeat: 3, ease: 'sine.inOut' })
          .to(dots, { attr: { cx: 24, cy: 52 }, duration: 0.45, ease: 'power3.inOut' })
          .to([dots[1], dots[2]], { opacity: 0, duration: 0.1 })
          .to('#fMarkA', { strokeDashoffset: 0, duration: 0.6, ease: 'power3.out' }, '-=.05')
          .to(dots[0], { opacity: 0, attr: { r: 5.5 }, duration: 0.3, ease: 'back.out(3)' }, '<')
          .to('#fMarkB', { strokeDashoffset: 0, duration: 0.5, ease: 'power3.out' }, '-=.2')
          .to('#fRing', { strokeDashoffset: 0, duration: 0.9, ease: 'power2.inOut' }, '-=.3');
      }

      ScrollTrigger.refresh();
    };

    // ── Generated scenery + intro timeline ────────────────────────────────
    const ctx = gsap.context(() => {
      buildSqFields(root, reduceMotion);
      buildGlass(root);
      buildPetals(root);

      if (reduceMotion) {
        // Final state immediately; no intro, no scroll lock.
        root.removeAttribute('data-intro');
        gsap.set('.bloom-app', { clearProps: 'all' });
        root.querySelector('.backdrop')?.remove();
        setupScroll();
        return;
      }

      lenis.stop();

      const intro = gsap.timeline({ delay: 0.25 });
      intro
        .fromTo(
          '.bloom-app',
          { scale: 0.9, borderRadius: 28 },
          { scale: 1, borderRadius: 0, duration: 1.4, ease: 'expo.inOut' },
        )
        .fromTo(
          ['.nav', '.github-pill'],
          { opacity: 0, y: -16 },
          { opacity: 1, y: 0, duration: 0.8, ease: 'power3.out' },
          '-=.5',
        )
        .fromTo(
          '#heroTitle .w',
          { opacity: 0, y: 24, filter: 'blur(10px)' },
          { opacity: 1, y: 0, filter: 'blur(0px)', duration: 1, stagger: 0.07, ease: 'power3.out' },
          '-=.7',
        )
        .fromTo(
          '.cloud-l',
          { x: -120, opacity: 0 },
          { x: 0, opacity: 1, duration: 1.6, ease: 'power3.out' },
          0.4,
        )
        .fromTo(
          '.cloud-r',
          { x: 120, opacity: 0 },
          { x: 0, opacity: 1, duration: 1.6, ease: 'power3.out' },
          0.4,
        )
        .fromTo(
          '#heroGlass .glass',
          { opacity: 0, scale: 0.6 },
          {
            opacity: 1,
            scale: 1,
            duration: 0.6,
            stagger: { each: 0.05, from: 'random' },
            ease: 'back.out(2)',
          },
          '-=1',
        );

      intro.eventCallback('onComplete', () => {
        root.removeAttribute('data-intro');
        gsap.set('.bloom-app', { clearProps: 'all' });
        root.querySelector('.backdrop')?.remove();
        lenis.start();
        scrollCtx = gsap.context(() => setupScroll(), root);
      });
    }, root);

    const onWindowLoad = () => ScrollTrigger.refresh();
    window.addEventListener('load', onWindowLoad);

    // ── Full teardown on any client navigation away from `/` ──────────────
    return () => {
      window.removeEventListener('load', onWindowLoad);
      root.removeEventListener('click', onAnchorClick);
      // Release the #loop gate before anything is destroyed: no wheel
      // preventDefault or frozen Lenis instance may survive navigation.
      settleCall?.kill();
      stepObserver?.kill();
      stepObserver = null;
      releaseLoopGate = null;
      lenis.start();
      media?.revert();
      scrollCtx?.revert();
      ctx.revert();
      lenis.destroy();
      gsap.ticker.remove(tick);
      gsap.ticker.lagSmoothing(0);
      ScrollTrigger.getAll().forEach((trigger) => trigger.kill());
      document.body.classList.remove('bloom-page');
    };
  }, []);

  return (
    <div className="bloom" data-intro="true" ref={rootRef}>
      <div className="backdrop" aria-hidden="true" />

      <div className="bloom-app">
        <BloomHero />
        <BloomStats />
        <BloomPreview />
        <BloomModels />
        <BloomLoop />
        <BloomCta />
        <BloomFooter />
      </div>
    </div>
  );
}
