import React from 'react';

export interface MicroSlatsProps {
  preset?: 'swell' | 'tide' | 'storm' | 'signal';
  color?: string;
  glintColor?: string;
  backgroundColor?: string;
  slatWidth?: number;
  slatHeight?: number;
  gap?: number;
  roundness?: number;
  scale?: number;
  speed?: number;
  direction?: number;
  chop?: number;
  stretch?: number;
  glint?: number;
  contrast?: number;
  perspective?: number;
  fog?: number;
  interactive?: boolean;
  cursorStrength?: number;
  cursorSize?: number;
  swirl?: number;
  trail?: number;
  lean?: number;
  intro?: boolean;
  introDuration?: number;
  paused?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

declare const MicroSlats: React.FC<MicroSlatsProps>;
export default MicroSlats;
