import React from 'react';

export interface LetterGlitchProps {
  glitchColors?: string[];
  className?: string;
  glitchSpeed?: number;
  centerVignette?: boolean;
  outerVignette?: boolean;
  smooth?: boolean;
  characters?: string;
}

declare const LetterGlitch: React.FC<LetterGlitchProps>;
export default LetterGlitch;
