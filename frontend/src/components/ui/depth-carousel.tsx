'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import gsap from 'gsap';
import './depth-carousel.css';

export interface DepthCarouselSlide {
  /** Optional image used when the card is rendered without custom content. */
  image?: string;
  alt?: string;
  /** Optional rich content rendered inside the card instead of an image. */
  content?: ReactNode;
}

export type DepthCarouselItem = string | DepthCarouselSlide;

export interface DepthCarouselProps {
  /** Slides to display. Pass image URLs or objects with an image URL and alt text. */
  items?: DepthCarouselItem[];
  /** Width of each card in pixels. */
  cardWidth?: number;
  /** Height of each card in pixels. */
  cardHeight?: number;
  /** Corner rounding of the cards in pixels. */
  radius?: number;
  /** Colour multiplied over cards as they recede. */
  tint?: string;
  /** Z distance in pixels between each card along the depth rail. */
  depth?: number;
  /** Lateral offset in pixels applied per card. */
  spread?: number;
  /** Degrees each receding card rotates around the vertical axis. */
  tilt?: number;
  /** Which side the stack fans and tilts toward. */
  tiltDirection?: 'left' | 'right';
  /** CSS perspective in pixels. */
  perspective?: number;
  /** How many cards deep remain visible before further ones fade out. */
  visibleCards?: number;
  /**
   * How the card stack is scaled to the available width.
   * - `stack`: the whole fan of cards is scaled to fit (default).
   * - `card`: a single card is scaled to the available width, which keeps
   *   text-heavy cards readable on small viewports.
   */
  scaleMode?: 'stack' | 'card';
  /** Optional custom card renderer; receives the slide and its index. */
  renderCard?: (item: DepthCarouselSlide, index: number) => ReactNode;
  /** How quickly brightness, tint and blur ramp up with depth. */
  falloff?: number;
  /** Maximum blur in pixels applied to the furthest visible card. */
  blur?: number;
  /** Length of the advance transition in milliseconds. */
  duration?: number;
  /** GSAP easing used for navigation transitions. */
  ease?: string;
  /** Auto-advance the carousel, pausing on hover or focus. */
  autoplay?: boolean;
  /** Delay between auto-advances in milliseconds. */
  autoplayDelay?: number;
  /** Wrap seamlessly from the last card back to the first. */
  loop?: boolean;
  /** Show the previous / next arrow buttons. */
  showControls?: boolean;
  /** Show the dot indicators. */
  showIndicators?: boolean;
  /**
   * Optional controlled focused index. When provided, the carousel follows the
   * value (quick-jump tabs) while still reporting internal drag / wheel
   * movement through `onChange`.
   */
  index?: number;
  /** Called whenever the focused card changes. */
  onChange?: (index: number, item: DepthCarouselSlide) => void;
  /** Accessible name for the carousel region. */
  ariaLabel?: string;
  className?: string;
}

const DEFAULT_ITEMS: DepthCarouselSlide[] = [
  { image: 'https://picsum.photos/seed/depth1/800/1000', alt: 'Slide 1' },
  { image: 'https://picsum.photos/seed/depth2/800/1000', alt: 'Slide 2' },
  { image: 'https://picsum.photos/seed/depth3/800/1000', alt: 'Slide 3' },
  { image: 'https://picsum.photos/seed/depth4/800/1000', alt: 'Slide 4' },
  { image: 'https://picsum.photos/seed/depth5/800/1000', alt: 'Slide 5' },
  { image: 'https://picsum.photos/seed/depth6/800/1000', alt: 'Slide 6' },
];

/** Extra room kept free around a single card when `scaleMode` is `card`. */
const CARD_FIT_PADDING = 48;

interface DepthCarouselConfig {
  count: number;
  depth: number;
  spread: number;
  tilt: number;
  tiltDirection: 'left' | 'right';
  visibleCards: number;
  falloff: number;
  blur: number;
  duration: number;
  ease: string;
  loop: boolean;
  cardWidth: number;
  autoplayDelay: number;
  scaleMode: 'stack' | 'card';
}

interface DragState {
  x: number;
  startPos: number;
  lastX: number;
  lastT: number;
  v: number;
  moved: boolean;
  id: number;
}

const clamp = (v: number, min: number, max: number) =>
  Math.min(Math.max(v, min), max);

const normalizeItem = (item: DepthCarouselItem): DepthCarouselSlide =>
  typeof item === 'string' ? { image: item, alt: '' } : item;

const DepthCarousel = ({
  items = DEFAULT_ITEMS,
  cardWidth = 300,
  cardHeight = 380,
  radius = 18,
  tint = '#05060a',
  depth = 220,
  spread = 90,
  tilt = 22,
  tiltDirection = 'right',
  perspective = 1400,
  visibleCards = 4,
  scaleMode = 'stack',
  renderCard,
  falloff = 0.2,
  blur = 6,
  duration = 700,
  ease = 'power3.out',
  autoplay = false,
  autoplayDelay = 3200,
  loop = true,
  showControls = true,
  showIndicators = true,
  index,
  onChange,
  ariaLabel = 'Depth carousel',
  className = '',
}: DepthCarouselProps) => {
  const data = useMemo(
    () => (Array.isArray(items) ? items : []).map(normalizeItem),
    [items],
  );
  const count = data.length;

  // Integer (even) card dimensions keep every card on whole pixels so the
  // browser never has to rasterize a half-pixel subpixel offset.
  const cardW = Math.round(cardWidth / 2) * 2;
  const cardH = Math.round(cardHeight / 2) * 2;

  const rootRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);
  const overlayRefs = useRef<(HTMLSpanElement | null)[]>([]);

  const posRef = useRef(0);
  const focusRef = useRef(0);
  const tweenRef = useRef<gsap.core.Tween | null>(null);
  const scaleRef = useRef(1);
  const cfgRef = useRef<DepthCarouselConfig>({
    count: 0,
    depth,
    spread,
    tilt,
    tiltDirection,
    visibleCards,
    falloff,
    blur,
    duration,
    ease,
    loop,
    cardWidth: cardW,
    autoplayDelay,
    scaleMode,
  });
  const onChangeRef = useRef<DepthCarouselProps['onChange']>(onChange);

  const dragRef = useRef<DragState | null>(null);
  const wheelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const autoTimerRef = useRef<number | null>(null);
  const reducedRef = useRef(false);

  /**
   * Tracks the last index handed to (or reported by) the carousel so that a
   * controlled `index` never bounces back and forth with `onChange`.
   */
  const lastSyncedIndexRef = useRef<number | null>(null);

  const [active, setActive] = useState(0);

  // Keep the mutable configuration in sync after every commit. Reading and
  // writing refs during render is not allowed under the React Compiler rules,
  // so the sync happens in an effect that always runs before the layout and
  // navigation effects declared below it.
  useEffect(() => {
    onChangeRef.current = onChange;
    cfgRef.current = {
      count,
      depth,
      spread,
      tilt,
      tiltDirection,
      visibleCards,
      falloff,
      blur,
      duration,
      ease,
      loop,
      cardWidth: cardW,
      autoplayDelay,
      scaleMode,
    };
  });

  const layout = useCallback((pos: number) => {
    const cfg = cfgRef.current;
    const n = cfg.count;
    if (!n) return;
    const dir = cfg.tiltDirection === 'left' ? -1 : 1;
    const sc = scaleRef.current;

    for (let i = 0; i < n; i += 1) {
      const el = cardRefs.current[i];
      if (!el) continue;

      let d = i - pos;
      if (cfg.loop && n > 1) {
        d = ((d % n) + n) % n;
        if (d > n / 2) d -= n;
      }

      const back = Math.max(0, d);
      const az = Math.abs(d);
      const shown = az <= cfg.visibleCards + 0.5;

      const tz = -cfg.depth * d;
      const tx = dir * cfg.spread * d;
      const ry = dir * cfg.tilt * clamp(d, 0, 1);

      let opacity = d < 0 ? Math.max(0, 1 + d) : 1;
      if (!shown) opacity = 0;

      const brightness = Math.max(0.15, 1 - back * cfg.falloff);
      const blurPx =
        cfg.blur > 0
          ? Math.min(
              cfg.blur,
              (back / Math.max(1, cfg.visibleCards)) * cfg.blur,
            )
          : 0;
      const zi = Math.round(2000 - d * 20);

      // A card is only "settled front" when it is exactly at the focus point
      // AND rendered at native scale. In that state we drop every 3D transform
      // and filter so the browser paints it as flat 2D at 1:1 resolution.
      const isSettledFront =
        Math.abs(d) < 0.001 && Math.abs(sc - 1) < 0.001;
      el.classList.toggle('is-front', isSettledFront);
      el.classList.toggle('is-active', isSettledFront);

      if (isSettledFront) {
        el.style.transform = 'none';
        el.style.filter = 'none';
        el.style.willChange = 'auto';
      } else {
        const isAnimating = Math.abs(d) >= 0.001;
        // Receding / animating cards keep the full 3D transform. The stage now
        // centers cards without a -50% offset, so no translate(-50%) term is
        // needed here.
        if (isAnimating || d > 0) {
          el.style.transform = `scale(${sc}) translateX(${tx.toFixed(2)}px) translateZ(${tz.toFixed(2)}px) rotateY(${ry.toFixed(3)}deg)`;
          el.style.filter = `brightness(${brightness.toFixed(3)}) blur(${blurPx.toFixed(2)}px)`;
          el.style.willChange = 'transform, opacity, filter';
        } else {
          // Settled but scaled (e.g. mobile): keep it flat and sharp.
          el.style.transform = `scale(${sc})`;
          el.style.filter = 'none';
          el.style.willChange = 'transform';
        }
      }
      el.style.opacity = opacity.toFixed(3);
      el.style.zIndex = String(zi);
      el.style.pointerEvents = shown && opacity > 0.05 ? 'auto' : 'none';

      const ov = overlayRefs.current[i];
      if (ov) {
        ov.style.opacity = clamp(
          back * cfg.falloff * 1.25,
          0,
          0.86,
        ).toFixed(3);
      }
    }
  }, []);

  const notify = useCallback(
    (idx: number) => {
      lastSyncedIndexRef.current = idx;
      setActive(idx);
      onChangeRef.current?.(idx, data[idx]);
    },
    [data],
  );

  const tweenTo = useCallback(
    (target: number, animate: boolean) => {
      tweenRef.current?.kill();
      const cfg = cfgRef.current;
      const proxy = { p: posRef.current };
      const dur = animate && !reducedRef.current ? cfg.duration / 1000 : 0;
      tweenRef.current = gsap.to(proxy, {
        p: target,
        duration: dur,
        ease: cfg.ease,
        onUpdate: () => {
          posRef.current = proxy.p;
          layout(proxy.p);
        },
        onComplete: () => {
          const n = cfg.count;
          if (n > 0) posRef.current = ((posRef.current % n) + n) % n;
          layout(posRef.current);
        },
      });
    },
    [layout],
  );

  const setFocus = useCallback(
    (rawIndex: number, animate = true) => {
      const cfg = cfgRef.current;
      const n = cfg.count;
      if (!n) return;
      const idx = cfg.loop
        ? ((rawIndex % n) + n) % n
        : clamp(rawIndex, 0, n - 1);
      let delta = idx - posRef.current;
      if (cfg.loop && n > 1) {
        delta = ((delta % n) + n) % n;
        if (delta > n / 2) delta -= n;
      }
      tweenTo(posRef.current + delta, animate);
      if (idx !== focusRef.current) {
        focusRef.current = idx;
        notify(idx);
      }
    },
    [tweenTo, notify],
  );

  const navigateBy = useCallback(
    (step: number) => setFocus(focusRef.current + step, true),
    [setFocus],
  );

  // Controlled index: follow external jumps (quick-jump tabs) exactly once.
  // `lastSyncedIndexRef` is updated by `notify` for internal movement, so a
  // drag/wheel change reported through `onChange` can never bounce back.
  useEffect(() => {
    if (index == null) return;
    const n = cfgRef.current.count;
    if (!n) return;
    const target = ((index % n) + n) % n;
    if (lastSyncedIndexRef.current === target) return;
    lastSyncedIndexRef.current = target;
    if (target !== focusRef.current) {
      setFocus(target, true);
    }
  }, [index, setFocus]);

  const updateScale = useCallback(() => {
    const root = rootRef.current;
    if (!root) return;
    const w = root.getBoundingClientRect().width;
    const cfg = cfgRef.current;
    const needed =
      cfg.scaleMode === 'card'
        ? cfg.cardWidth + CARD_FIT_PADDING
        : cfg.cardWidth + Math.abs(cfg.spread) * 2 + 120;
    scaleRef.current = clamp(w / needed, 0.4, 1);
    layout(posRef.current);
  }, [layout]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const ro = new ResizeObserver(() => updateScale());
    ro.observe(root);
    return () => ro.disconnect();
  }, [updateScale]);

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const cfg = cfgRef.current;
      if (cfg.count < 2) return;
      e.preventDefault();
      tweenRef.current?.kill();
      const raw =
        Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      const delta = e.deltaMode === 1 ? raw * 24 : raw;
      const step = clamp(
        delta / (cfg.cardWidth * 0.9),
        -0.6,
        0.6,
      );
      posRef.current += step;
      layout(posRef.current);
      if (wheelTimerRef.current) clearTimeout(wheelTimerRef.current);
      wheelTimerRef.current = setTimeout(
        () => setFocus(Math.round(posRef.current), true),
        130,
      );
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      el.removeEventListener('wheel', onWheel);
      if (wheelTimerRef.current) clearTimeout(wheelTimerRef.current);
    };
  }, [layout, setFocus]);

  const onPointerDown = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    const cfg = cfgRef.current;
    if (cfg.count < 2) return;
    tweenRef.current?.kill();
    dragRef.current = {
      x: e.clientX,
      startPos: posRef.current,
      lastX: e.clientX,
      lastT: performance.now(),
      v: 0,
      moved: false,
      id: e.pointerId,
    };
  }, []);

  const onPointerMove = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag) return;
      const cfg = cfgRef.current;
      const stepPx = Math.max(
        cfg.cardWidth * 0.55 * scaleRef.current,
        40,
      );
      const dx = e.clientX - drag.x;
      if (!drag.moved && Math.abs(dx) > 4) {
        drag.moved = true;
        rootRef.current?.setPointerCapture(drag.id);
      }
      if (!drag.moved) return;
      const now = performance.now();
      const dt = Math.max(now - drag.lastT, 1);
      drag.v = (e.clientX - drag.lastX) / dt;
      drag.lastX = e.clientX;
      drag.lastT = now;
      posRef.current = drag.startPos - dx / stepPx;
      layout(posRef.current);
    },
    [layout],
  );

  const onPointerEnd = useCallback(() => {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    if (!drag.moved) return;
    const cfg = cfgRef.current;
    const stepPx = Math.max(
      cfg.cardWidth * 0.55 * scaleRef.current,
      40,
    );
    const projected = posRef.current - (drag.v * 180) / stepPx;
    setFocus(Math.round(projected), true);
  }, [setFocus]);

  const onKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        navigateBy(-1);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        navigateBy(1);
      }
    },
    [navigateBy],
  );

  const onCardClick = useCallback(
    (cardIndex: number) => {
      if (dragRef.current?.moved) return;
      setFocus(cardIndex, true);
    },
    [setFocus],
  );

  useEffect(() => {
    reducedRef.current =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!autoplay || reducedRef.current || count < 2) return;
    const root = rootRef.current;
    let hovered = false;
    let focused = false;
    const stop = () => {
      if (autoTimerRef.current !== null) {
        window.clearInterval(autoTimerRef.current);
      }
      autoTimerRef.current = null;
    };
    const start = () => {
      stop();
      autoTimerRef.current = window.setInterval(
        () => {
          if (!hovered && !focused) navigateBy(1);
        },
        Math.max(cfgRef.current.autoplayDelay, 600),
      );
    };
    const onEnter = () => {
      hovered = true;
    };
    const onLeave = () => {
      hovered = false;
    };
    const onFocusIn = () => {
      focused = true;
    };
    const onFocusOut = () => {
      focused = false;
    };
    root?.addEventListener('mouseenter', onEnter);
    root?.addEventListener('mouseleave', onLeave);
    root?.addEventListener('focusin', onFocusIn);
    root?.addEventListener('focusout', onFocusOut);
    start();
    return () => {
      stop();
      root?.removeEventListener('mouseenter', onEnter);
      root?.removeEventListener('mouseleave', onLeave);
      root?.removeEventListener('focusin', onFocusIn);
      root?.removeEventListener('focusout', onFocusOut);
    };
  }, [autoplay, autoplayDelay, count, navigateBy]);

  useEffect(() => {
    updateScale();
  }, [
    updateScale,
    depth,
    spread,
    tilt,
    tiltDirection,
    visibleCards,
    falloff,
    blur,
    cardWidth,
    cardHeight,
    radius,
    count,
    scaleMode,
  ]);

  useEffect(
    () => () => {
      tweenRef.current?.kill();
      if (wheelTimerRef.current) clearTimeout(wheelTimerRef.current);
      if (autoTimerRef.current !== null) {
        window.clearInterval(autoTimerRef.current);
      }
    },
    [],
  );

  return (
    <div
      ref={rootRef}
      className={`depth-carousel ${className}`.trim()}
      style={{ '--dc-perspective': `${perspective}px` } as CSSProperties}
      role="group"
      aria-roledescription="carousel"
      aria-label={ariaLabel}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerEnd}
      onPointerCancel={onPointerEnd}
      onKeyDown={onKeyDown}
    >
      <div className="depth-carousel__stage" ref={stageRef}>
        {data.map((item, i) => {
          const hasCustomContent =
            renderCard !== undefined || item.content !== undefined;
          return (
            <div
              key={i}
              className="depth-carousel__card"
              ref={(el) => {
                cardRefs.current[i] = el;
              }}
              style={{ width: cardW, height: cardH, borderRadius: radius }}
              aria-roledescription="slide"
              aria-label={`${i + 1} of ${count}`}
              aria-hidden={active !== i}
              onClick={() => onCardClick(i)}
            >
              {hasCustomContent ? (
                renderCard ? (
                  renderCard(item, i)
                ) : (
                  item.content
                )
              ) : item.image ? (
                /* eslint-disable-next-line @next/next/no-img-element -- arbitrary remote/local image URLs are supported by design */
                <img
                  className="depth-carousel__img"
                  src={item.image}
                  alt={item.alt || ''}
                  draggable={false}
                />
              ) : null}
              <span
                className="depth-carousel__tint"
                ref={(el) => {
                  overlayRefs.current[i] = el;
                }}
                style={{ background: tint }}
              />
            </div>
          );
        })}
      </div>

      {showControls && count > 1 && (
        <>
          <button
            type="button"
            className="depth-carousel__arrow depth-carousel__arrow--prev"
            aria-label="Previous slide"
            onClick={() => navigateBy(-1)}
          >
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path
                d="M15 5l-7 7 7 7"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <button
            type="button"
            className="depth-carousel__arrow depth-carousel__arrow--next"
            aria-label="Next slide"
            onClick={() => navigateBy(1)}
          >
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
              <path
                d="M9 5l7 7-7 7"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </>
      )}

      {showIndicators && count > 1 && (
        <div
          className="depth-carousel__dots"
          role="tablist"
          aria-label="Slides"
        >
          {data.map((_, i) => (
            <button
              key={i}
              type="button"
              role="tab"
              aria-selected={active === i}
              aria-label={`Go to slide ${i + 1}`}
              className={`depth-carousel__dot${active === i ? ' is-active' : ''}`}
              onClick={() => setFocus(i, true)}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default DepthCarousel;
