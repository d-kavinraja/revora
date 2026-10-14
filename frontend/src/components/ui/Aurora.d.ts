import React from 'react';

export interface AuroraProps {
  /** Two to five colors that blend across the aurora from left to right. */
  colorStops?: string[];
  /** How tall the waves along the edge are. */
  amplitude?: number;
  /** How softly the edge fades out, from 0 to 1. */
  blend?: number;
  /** Speed of the flowing motion. */
  speed?: number;
  /** External clock (e.g. scroll progress) that drives the animation instead of real time. */
  time?: number;
  /** How far the aurora reaches into the container, from 0 to 1. */
  height?: number;
  /** Size of the waves. Lower values make broader, calmer shapes. */
  scale?: number;
  /** How far the light spills softly past the edge. */
  glow?: number;
  /** Overall brightness of the light. */
  brightness?: number;
  /** Number of curtains, from 1 to 3. */
  layers?: number;
  /** Whether the aurora hangs from the top or rises from the bottom. */
  direction?: 'top' | 'bottom';
  /** The light gently reaches toward the cursor. */
  mouseInteraction?: boolean;
  /** Fades the aurora in as it unfurls on mount. */
  intro?: boolean;
  /** Opacity of the whole effect. */
  opacity?: number;
  /** Draws the aurora as soft pastel light for white backgrounds. */
  lightMode?: boolean;
  /** Freezes the animation. */
  paused?: boolean;
  /** Maximum device pixel ratio, capped at 2. */
  dpr?: number;
  /** Extra class names for the container. */
  className?: string;
  /** Inline styles for the container. */
  style?: React.CSSProperties;
}

declare const Aurora: React.FC<AuroraProps>;
export default Aurora;
