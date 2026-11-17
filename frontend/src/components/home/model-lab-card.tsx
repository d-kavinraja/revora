'use client';

import { useState, useRef, useCallback, type MouseEvent } from 'react';
import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import './model-lab-card.css';

export function ModelLabCard() {
  const cardRef = useRef<HTMLDivElement>(null);
  const [rotate, setRotate] = useState({ x: 0, y: 0 });
  const [isHovered, setIsHovered] = useState(false);

  const handleMouseMove = useCallback((e: MouseEvent<HTMLDivElement>) => {
    // Only apply tilt on desktop screens (>1024px)
    if (typeof window !== 'undefined' && window.innerWidth <= 1024) return;
    if (!cardRef.current) return;

    const rect = cardRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    const centerX = rect.width / 2;
    const centerY = rect.height / 2;

    // Max 6deg tilt
    const rotateX = ((centerY - y) / centerY) * 6;
    const rotateY = ((x - centerX) / centerX) * 6;

    setRotate({ x: rotateX, y: rotateY });
  }, []);

  const handleMouseEnter = useCallback(() => {
    setIsHovered(true);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setIsHovered(false);
    setRotate({ x: 0, y: 0 });
  }, []);

  return (
    <div className="ml-card-wrapper ml-entrance-anim">
      <div
        ref={cardRef}
        className="ml-card-border-glow"
        onMouseMove={handleMouseMove}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        style={{
          transform: isHovered
            ? `rotateX(${rotate.x}deg) rotateY(${rotate.y}deg) translateZ(8px)`
            : 'rotateX(0deg) rotateY(0deg) translateZ(0px)',
        }}
      >
        <div className="ml-card-inner">
          {/* Visual header: Interactive Mini Neural Network */}
          <div className="ml-media-header" aria-hidden="true">
            {/* Texture overlay: faint dotted grid & scanlines */}
            <div className="ml-grid-texture" />

            {/* Neural network SVG */}
            <svg
              className="ml-neural-svg"
              viewBox="0 0 300 120"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <defs>
                <linearGradient id="edgeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#ff5a2c" stopOpacity="0.15" />
                  <stop offset="50%" stopColor="#f6b48a" stopOpacity="0.45" />
                  <stop offset="100%" stopColor="#ff5a2c" stopOpacity="0.15" />
                </linearGradient>

                <linearGradient id="aiGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#ff7c55" />
                  <stop offset="100%" stopColor="#c2260f" />
                </linearGradient>

                <filter id="glowFilter" x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="3.5" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>

              {/* Connections (Layer 1 -> Layer 2) */}
              {/* L1 nodes: (45, 25), (45, 60), (45, 95) */}
              {/* L2 nodes: (150, 20), (150, 60 [AI Center]), (150, 100) */}
              <path id="path-1" d="M 45 25 Q 97 18 150 20" stroke="url(#edgeGrad)" strokeWidth="1" />
              <path id="path-2" d="M 45 25 Q 97 42 150 60" stroke="url(#edgeGrad)" strokeWidth="1.2" />
              <path id="path-3" d="M 45 60 Q 97 40 150 20" stroke="url(#edgeGrad)" strokeWidth="1" />
              <path id="path-4" d="M 45 60 L 150 60" stroke="url(#edgeGrad)" strokeWidth="1.4" />
              <path id="path-5" d="M 45 60 Q 97 80 150 100" stroke="url(#edgeGrad)" strokeWidth="1" />
              <path id="path-6" d="M 45 95 Q 97 78 150 60" stroke="url(#edgeGrad)" strokeWidth="1.2" />
              <path id="path-7" d="M 45 95 Q 97 102 150 100" stroke="url(#edgeGrad)" strokeWidth="1" />

              {/* Connections (Layer 2 -> Layer 3) */}
              {/* L3 nodes: (255, 38), (255, 82) */}
              <path id="path-8" d="M 150 20 Q 202 26 255 38" stroke="url(#edgeGrad)" strokeWidth="1" />
              <path id="path-9" d="M 150 20 Q 202 54 255 82" stroke="url(#edgeGrad)" strokeWidth="1" />
              <path id="path-10" d="M 150 60 Q 202 46 255 38" stroke="url(#edgeGrad)" strokeWidth="1.4" />
              <path id="path-11" d="M 150 60 Q 202 74 255 82" stroke="url(#edgeGrad)" strokeWidth="1.4" />
              <path id="path-12" d="M 150 100 Q 202 66 255 38" stroke="url(#edgeGrad)" strokeWidth="1" />
              <path id="path-13" d="M 150 100 Q 202 94 255 82" stroke="url(#edgeGrad)" strokeWidth="1" />

              {/* Animated pulse dots travelling along neural pathways */}
              <circle r="2.2" fill="#ff5a2c" filter="url(#glowFilter)" className="ml-neural-pulse">
                <animateMotion dur="2.4s" repeatCount="indefinite" path="M 45 25 Q 97 42 150 60" />
              </circle>
              <circle r="2" fill="#f6b48a" filter="url(#glowFilter)" className="ml-neural-pulse">
                <animateMotion dur="2.8s" begin="0.8s" repeatCount="indefinite" path="M 45 60 L 150 60" />
              </circle>
              <circle r="2.2" fill="#ff5a2c" filter="url(#glowFilter)" className="ml-neural-pulse">
                <animateMotion dur="2.6s" begin="0.4s" repeatCount="indefinite" path="M 45 95 Q 97 78 150 60" />
              </circle>
              <circle r="2" fill="#f6b48a" filter="url(#glowFilter)" className="ml-neural-pulse">
                <animateMotion dur="2.2s" begin="1.2s" repeatCount="indefinite" path="M 150 60 Q 202 46 255 38" />
              </circle>
              <circle r="2.2" fill="#ff5a2c" filter="url(#glowFilter)" className="ml-neural-pulse">
                <animateMotion dur="2.5s" begin="0.6s" repeatCount="indefinite" path="M 150 60 Q 202 74 255 82" />
              </circle>

              {/* Layer 1 Nodes (Input) */}
              <circle cx="45" cy="25" r="4" fill="#1b0b08" stroke="#ff5a2c" strokeWidth="1.5" />
              <circle cx="45" cy="25" r="1.5" fill="#f6b48a" />

              <circle cx="45" cy="60" r="4" fill="#1b0b08" stroke="#ff5a2c" strokeWidth="1.5" />
              <circle cx="45" cy="60" r="1.5" fill="#f6b48a" />

              <circle cx="45" cy="95" r="4" fill="#1b0b08" stroke="#ff5a2c" strokeWidth="1.5" />
              <circle cx="45" cy="95" r="1.5" fill="#f6b48a" />

              {/* Layer 2 Nodes (Hidden layer) */}
              <circle cx="150" cy="20" r="4" fill="#1b0b08" stroke="#ff5a2c" strokeWidth="1.5" />
              <circle cx="150" cy="20" r="1.5" fill="#f6b48a" />

              <circle cx="150" cy="100" r="4" fill="#1b0b08" stroke="#ff5a2c" strokeWidth="1.5" />
              <circle cx="150" cy="100" r="1.5" fill="#f6b48a" />

              {/* Layer 2 Center Node: "AI" with breathing glow */}
              <circle
                cx="150"
                cy="60"
                r="18"
                className="ml-ai-node-glow"
                filter="url(#glowFilter)"
              />
              <circle cx="150" cy="60" r="13" fill="url(#aiGrad)" stroke="#f6b48a" strokeWidth="1.5" />
              <text
                x="150"
                y="63.5"
                textAnchor="middle"
                fill="#ffffff"
                fontSize="8.5"
                fontWeight="800"
                fontFamily="var(--font-jetbrains-mono, monospace)"
                letterSpacing="0.08em"
              >
                AI
              </text>

              {/* Layer 3 Nodes (Output) */}
              <circle cx="255" cy="38" r="4" fill="#1b0b08" stroke="#ff5a2c" strokeWidth="1.5" />
              <circle cx="255" cy="38" r="1.5" fill="#f6b48a" />

              <circle cx="255" cy="82" r="4" fill="#1b0b08" stroke="#ff5a2c" strokeWidth="1.5" />
              <circle cx="255" cy="82" r="1.5" fill="#f6b48a" />
            </svg>

            {/* Restyled "NEW" gradient pill badge with pulsing dot */}
            <div className="ml-badge-pill">
              <span className="ml-badge-dot" />
              <span className="ml-badge-text">NEW</span>
            </div>
          </div>

          {/* Content details */}
          <div className="ml-content-body">
            <h3 className="ml-title">
              Model Lab is <span className="ml-title-gradient">live</span>
            </h3>
            <p className="ml-subtext">
              Build, test, and manage custom AI &amp; deep learning models — free.
            </p>

            {/* 3 Compact feature chips */}
            <div className="ml-chips-row" role="list" aria-label="Key features">
              <span className="ml-chip" role="listitem">Train</span>
              <span className="ml-chip" role="listitem">Evaluate</span>
              <span className="ml-chip" role="listitem">Deploy</span>
            </div>

            {/* Status row: Green pulsing dot + Beta label */}
            <div className="ml-status-row" aria-label="Status: Beta, Free forever">
              <div className="ml-status-dot-wrap">
                <span className="ml-status-dot-ping" />
                <span className="ml-status-dot" />
              </div>
              <span>Beta · Free forever</span>
            </div>
          </div>

          {/* CTA Button */}
          <Link href="/model-lab" className="ml-cta-btn" aria-label="Try Model Lab free">
            <span>Try it free</span>
            <ArrowRight size={15} strokeWidth={2.4} aria-hidden="true" className="ml-cta-arrow" />
            <div className="ml-cta-shimmer" aria-hidden="true" />
          </Link>
        </div>
      </div>
    </div>
  );
}
