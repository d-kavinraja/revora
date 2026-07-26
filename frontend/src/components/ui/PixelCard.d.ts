import React from 'react';

export interface PixelCardProps {
  variant?: 'default' | 'blue' | 'yellow' | 'pink' | string;
  gap?: number;
  speed?: number;
  colors?: string;
  noFocus?: boolean;
  className?: string;
  style?: React.CSSProperties;
  children?: React.ReactNode;
}

declare const PixelCard: React.FC<PixelCardProps>;
export default PixelCard;
