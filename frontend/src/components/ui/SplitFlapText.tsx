'use client';

import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import './SplitFlapText.css';

const DEFAULT_WORDS = ['LAUNCH READY', 'SYNC ONLINE', 'SIGNAL LIVE'];

type CharsetName = 'alpha' | 'alphanumeric' | 'numeric';

const CHARSETS: Record<CharsetName, string> = {
  alpha: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
  alphanumeric: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
  numeric: '0123456789',
};

const toCssUnit = (value: number | string): string =>
  typeof value === 'number' ? `${value}px` : value;

const resolveCharset = (charset: CharsetName | string): string => {
  if (charset in CHARSETS) return CHARSETS[charset as CharsetName];
  return typeof charset === 'string' && charset.length > 0 ? charset : CHARSETS.alphanumeric;
};

const normalizePhrase = (phrase: string, width: number): string => {
  const safe = String(phrase ?? '');
  return safe.padEnd(width, ' ').slice(0, width);
};

interface TileState {
  current: string;
  next: string;
  flipping: boolean;
  tick: number;
}

const createTiles = (phrase: string): TileState[] =>
  phrase.split('').map((char) => ({
    current: char,
    next: char,
    flipping: false,
    tick: 0,
  }));

const sampleChar = (charset: string): string =>
  charset.charAt(Math.floor(Math.random() * charset.length)) || ' ';

const buildSequence = (target: string, flips: number, charset: string): string[] => {
  const steps: string[] = [];
  for (let i = 0; i < flips; i += 1) {
    steps.push(sampleChar(charset));
  }
  steps.push(target);
  return steps;
};

const usePrefersReducedMotion = (): boolean => {
  const [prefersReduced, setPrefersReduced] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;

    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handleChange = () => setPrefersReduced(mediaQuery.matches);

    handleChange();
    mediaQuery.addEventListener('change', handleChange);

    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  return prefersReduced;
};

interface FlipPlan {
  index: number;
  from: string;
  target: string;
  sequence: string[];
  start: number;
  step: number;
  done: boolean;
}

interface TileUpdate {
  index: number;
  current: string;
  next: string;
  done: boolean;
}

interface SplitFlapTextProps {
  words?: string[];
  text?: string;
  flipDuration?: number;
  stagger?: number;
  cycleDelay?: number;
  charset?: CharsetName | string;
  flipsPerChar?: number;
  tileColor?: string;
  textColor?: string;
  tileRadius?: number | string;
  gap?: number | string;
  fontSize?: number | string;
  loop?: boolean;
  padTo?: number;
  className?: string;
  style?: CSSProperties;
  [key: string]: unknown;
}

export default function SplitFlapText({
  words = ['LAUNCH READY', 'SYNC ONLINE', 'SIGNAL LIVE'],
  text,
  flipDuration = 0.12,
  stagger = 0.06,
  cycleDelay = 2400,
  charset = 'alphanumeric',
  flipsPerChar = 8,
  tileColor = '#111827',
  textColor = '#f8fafc',
  tileRadius = 8,
  gap = 6,
  fontSize = 52,
  loop = true,
  padTo = 12,
  className = '',
  style = {},
  ...props
}: SplitFlapTextProps) {
  const prefersReducedMotion = usePrefersReducedMotion();
  const rafRef = useRef<number | null>(null);
  const cycleTimerRef = useRef<number | null>(null);
  const currentTextRef = useRef<string>('');
  // Bumped for every animation run. A scheduled frame whose captured
  // generation is stale returns immediately, so at most one animation loop
  // can ever be live even if a frame is missed or a cleanup is raced.
  const generationRef = useRef(0);
  // Phrase set the animation was last seeded with; used to distinguish a real
  // phrase change (re-seed) from an incidental effect re-run (do not re-seed).
  const lastPhrasesKeyRef = useRef<string | null>(null);

  const sourceWords = Array.isArray(words) && words.length > 0 ? words : DEFAULT_WORDS;
  const phrasesKey =
    typeof text === 'string' ? text : sourceWords.map((word) => String(word ?? '')).join('\u001f');
  const phrases = useMemo(() => phrasesKey.split('\u001f'), [phrasesKey]);

  const width = useMemo(() => {
    const longest = phrases.reduce((max, phrase) => Math.max(max, phrase.length), 1);
    return Math.max(1, Math.ceil(Number(padTo) || 0), longest);
  }, [padTo, phrases]);

  const normalizedPhrases = useMemo(
    () => phrases.map((phrase) => normalizePhrase(phrase, width)),
    [phrases, width],
  );

  const [tiles, setTiles] = useState<TileState[]>(() => createTiles(normalizedPhrases[0] || ''));
  const [tileResetKey, setTileResetKey] = useState<string>(phrasesKey);

  // Render-phase reset when the phrase set changes (avoids setState in effect).
  if (tileResetKey !== phrasesKey) {
    setTileResetKey(phrasesKey);
    setTiles(createTiles(normalizedPhrases[0] || ''));
  }

  useEffect(() => {
    const cancelLoop = () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };

    const clearAnimation = () => {
      cancelLoop();

      if (cycleTimerRef.current) {
        clearTimeout(cycleTimerRef.current);
        cycleTimerRef.current = null;
      }
    };

    clearAnimation();

    const firstPhrase = normalizedPhrases[0] || '';
    // Re-seed the "current" text only when the phrase set itself changed.
    // Re-seeding on every effect re-run (for example when the
    // prefers-reduced-motion query resolves) would restart an in-flight
    // animation from the first phrase and produce a fresh burst of flips.
    if (lastPhrasesKeyRef.current !== phrasesKey) {
      lastPhrasesKeyRef.current = phrasesKey;
      currentTextRef.current = firstPhrase;
    }

    if (normalizedPhrases.length <= 1 || typeof window === 'undefined') {
      return clearAnimation;
    }

    let phraseIndex = 0;
    let cancelled = false;

    const safeFlipMs = Math.max(40, (Number(flipDuration) || 0.12) * 1000);
    const safeStaggerMs = Math.max(0, (Number(stagger) || 0) * 1000);
    const safeCycleDelay = Math.max(400, Number(cycleDelay) || 2400);
    const safeFlips = Math.max(0, Math.floor(Number(flipsPerChar) || 0));
    const activeCharset = resolveCharset(charset);

    const animateTo = (targetPhrase: string): number => {
      // Never leave a previous run alive: only one loop may run at a time.
      cancelLoop();
      const generation = generationRef.current + 1;
      generationRef.current = generation;

      if (prefersReducedMotion) {
        currentTextRef.current = targetPhrase;
        setTiles(createTiles(targetPhrase));
        return 0;
      }

      const fromPhrase = normalizePhrase(currentTextRef.current, width);
      const targetChars = targetPhrase.split('');

      const plans: FlipPlan[] = targetChars
        .map((targetChar, index) => {
          const fromChar = fromPhrase[index] || ' ';
          if (fromChar === targetChar) return null;

          return {
            index,
            from: fromChar,
            target: targetChar,
            sequence: buildSequence(targetChar, safeFlips, activeCharset),
            start: index * safeStaggerMs,
            step: -1,
            done: false,
          };
        })
        .filter((plan): plan is FlipPlan => plan !== null);

      if (!plans.length) {
        currentTextRef.current = targetPhrase;
        setTiles(createTiles(targetPhrase));
        return 0;
      }

      const totalDuration = plans.reduce(
        (max, plan) => Math.max(max, plan.start + plan.sequence.length * safeFlipMs),
        0,
      );
      const startedAt = performance.now();

      const updateTiles = (updates: TileUpdate[]) => {
        setTiles((previous) => {
          const nextTiles = previous.map((tile) => tile);
          let changed = false;

          updates.forEach((update) => {
            const tile = nextTiles[update.index];
            if (!tile) return;

            const flipping = !update.done;

            // Skip tiles whose rendered value is unchanged: returning the same
            // array lets React bail out of the re-render, and leaving `tick`
            // alone stops the flap spans (keyed by it) from remounting on
            // every frame.
            if (
              tile.current === update.current &&
              tile.next === update.next &&
              tile.flipping === flipping
            ) {
              return;
            }

            nextTiles[update.index] = {
              current: update.current,
              next: update.next,
              flipping,
              tick: tile.tick + 1,
            };
            changed = true;
          });

          return changed ? nextTiles : previous;
        });
      };

      const tick = (now: number) => {
        if (cancelled || generationRef.current !== generation) return;

        const elapsed = now - startedAt;
        const updates: TileUpdate[] = [];
        let shouldContinue = false;

        plans.forEach((plan) => {
          const localElapsed = elapsed - plan.start;

          if (localElapsed < 0) {
            shouldContinue = true;
            return;
          }

          const step = Math.floor(localElapsed / safeFlipMs);

          if (step < plan.sequence.length) {
            shouldContinue = true;

            if (step !== plan.step) {
              plan.step = step;
              updates.push({
                index: plan.index,
                current: step === 0 ? plan.from : plan.sequence[step - 1],
                next: plan.sequence[step],
                done: false,
              });
            }
          } else if (!plan.done) {
            plan.done = true;
            updates.push({
              index: plan.index,
              current: plan.target,
              next: plan.target,
              done: true,
            });
          }
        });

        if (updates.length > 0) updateTiles(updates);

        if (shouldContinue) {
          rafRef.current = requestAnimationFrame(tick);
        } else {
          currentTextRef.current = targetPhrase;
          rafRef.current = null;
        }
      };

      rafRef.current = requestAnimationFrame(tick);
      return totalDuration;
    };

    const scheduleNext = (delay: number) => {
      cycleTimerRef.current = window.setTimeout(() => {
        if (cancelled) return;

        // A hidden tab throttles or pauses requestAnimationFrame while timers
        // keep firing. Advancing here would start an animation that cannot run
        // to completion and strand a loop behind, so idle until visible again.
        if (document.hidden) {
          scheduleNext(safeCycleDelay);
          return;
        }

        const nextIndex = phraseIndex + 1;

        if (nextIndex >= normalizedPhrases.length && !loop) return;

        phraseIndex = nextIndex % normalizedPhrases.length;
        const animationDuration = animateTo(normalizedPhrases[phraseIndex]);
        scheduleNext(safeCycleDelay + animationDuration);
      }, delay);
    };

    scheduleNext(safeCycleDelay);

    return () => {
      cancelled = true;
      clearAnimation();
    };
  }, [
    normalizedPhrases,
    phrasesKey,
    width,
    loop,
    cycleDelay,
    flipDuration,
    stagger,
    flipsPerChar,
    charset,
    prefersReducedMotion,
  ]);

  const settledText = tiles
    .map((tile) => tile.current)
    .join('')
    .trimEnd();
  const componentStyle = {
    '--split-flap-tile-color': tileColor,
    '--split-flap-text-color': textColor,
    '--split-flap-radius': toCssUnit(tileRadius),
    '--split-flap-gap': toCssUnit(gap),
    '--split-flap-font-size': toCssUnit(fontSize),
    '--split-flap-flip-duration': `${Math.max(0.04, Number(flipDuration) || 0.12)}s`,
    ...style,
  } as CSSProperties;

  return (
    <div
      className={`split-flap-text ${className}`.trim()}
      style={componentStyle}
      role="text"
      aria-label={settledText || undefined}
      {...(props as Record<string, unknown>)}
    >
      {tiles.map((tile, index) => (
        <span className="split-flap-text__tile" aria-hidden="true" key={`${index}-${tiles.length}`}>
          <span className="split-flap-text__half split-flap-text__half--top">
            <span className="split-flap-text__char">{tile.current === ' ' ? '\u00A0' : tile.current}</span>
          </span>
          <span className="split-flap-text__half split-flap-text__half--bottom">
            <span className="split-flap-text__char">{tile.flipping ? tile.next : tile.current}</span>
          </span>

          {tile.flipping && (
            <>
              <span
                className="split-flap-text__flap split-flap-text__flap--front"
                key={`front-${index}-${tile.tick}`}
              >
                <span className="split-flap-text__char">
                  {tile.current === ' ' ? '\u00A0' : tile.current}
                </span>
              </span>
              <span
                className="split-flap-text__flap split-flap-text__flap--back"
                key={`back-${index}-${tile.tick}`}
              >
                <span className="split-flap-text__char">{tile.next === ' ' ? '\u00A0' : tile.next}</span>
              </span>
            </>
          )}
        </span>
      ))}
    </div>
  );
}
