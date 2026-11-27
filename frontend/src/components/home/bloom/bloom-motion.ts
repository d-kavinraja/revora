import { gsap } from 'gsap';

/**
 * DOM generators for the bloom landing page. All tweens created here are made
 * inside the caller's `gsap.context()`, so `ctx.revert()` cleans them up.
 * Generated nodes live inside React-managed containers and are removed with
 * the tree on unmount.
 */

/** Hero frosted-glass square positions: [x%, y%] — left / center / right. */
const GLASS_SQUARES: ReadonlyArray<readonly [number, number]> = [
  [3, 64],
  [3, 71],
  [6.5, 71],
  [10, 71],
  [3, 78],
  [-1, 70],
  [45.5, 76],
  [49, 80],
  [49, 76],
  [52.5, 76],
  [86, 58],
  [86, 67],
  [82, 76],
  [89.5, 76],
  [86, 84],
];

/** Faint flickering grid squares at the top of a section. */
export function buildSqFields(root: HTMLElement, reduceMotion: boolean): void {
  root.querySelectorAll<HTMLElement>('.sq-field').forEach((field) => {
    const count = Number(field.dataset.count ?? '0');
    for (let i = 0; i < count; i += 1) {
      const sq = document.createElement('div');
      sq.className = 'grid-sq';
      const col = Math.floor(Math.random() * 30);
      const row = Math.floor(Math.random() * 6);
      sq.style.width = '46px';
      sq.style.height = '46px';
      sq.style.left = `${col * 48 - 10}px`;
      sq.style.top = `${row * 48 + 6}px`;
      field.appendChild(sq);

      if (reduceMotion) {
        sq.style.opacity = '0.6';
      } else {
        sq.style.opacity = '0';
        gsap.to(sq, {
          opacity: 1,
          duration: 1.2,
          yoyo: true,
          repeat: -1,
          ease: 'sine.inOut',
          delay: Math.random() * 4,
          repeatDelay: Math.random() * 3,
        });
      }
    }
  });
}

/** Fifteen flickering frosted squares over the hero. */
export function buildGlass(root: HTMLElement): void {
  const host = root.querySelector<HTMLElement>('#heroGlass');
  if (!host) return;

  GLASS_SQUARES.forEach(([x, y], index) => {
    const sq = document.createElement('div');
    sq.className = 'glass';
    sq.style.left = `${x}%`;
    sq.style.top = `${y}%`;
    // Center cluster is smaller than the flanking clusters (per spec).
    sq.style.width = x > 40 && x < 60 ? 'clamp(28px, 3.4vw, 44px)' : 'clamp(36px, 5.4vw, 74px)';
    sq.style.aspectRatio = '1';
    if (index % 2 === 1) sq.classList.add('glass-odd');
    host.appendChild(sq);
  });
}

/** Starts the slow glass flicker after the intro entrance has finished. */
export function startGlassFlicker(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>('#heroGlass .glass').forEach((sq) => {
    gsap.to(sq, {
      opacity: 0.15,
      duration: 0.9,
      yoyo: true,
      repeat: -1,
      ease: 'sine.inOut',
      delay: Math.random() * 3,
      repeatDelay: 1 + Math.random() * 3,
    });
  });
}

/** Eighteen falling petals over the moonlit CTA valley. */
export function buildPetals(root: HTMLElement): void {
  const host = root.querySelector<HTMLElement>('#petals');
  if (!host) return;

  for (let i = 0; i < 18; i += 1) {
    const petal = document.createElement('span');
    petal.className = 'petal';
    petal.style.left = `${Math.random() * 100}%`;
    petal.style.setProperty('--dx', `${Math.round(Math.random() * 160 - 80)}px`);
    petal.style.setProperty('--s', (0.6 + Math.random() * 0.8).toFixed(2));
    petal.style.animationDuration = `${9 + Math.random() * 9}s`;
    petal.style.animationDelay = `-${Math.random() * 15}s`;
    host.appendChild(petal);
  }
}
