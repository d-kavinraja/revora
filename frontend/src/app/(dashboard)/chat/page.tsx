'use client';

import SideRays from '@/components/ui/SideRays';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { featureState, usePlatformFeatures } from '@/lib/use-platform-features';
import { useThemeStore } from '@/store/useThemeStore';

import { useEffect, useState } from 'react';
import { ChatShell } from './_components/chat-shell';

export default function ChatPage() {
  const { data: features } = usePlatformFeatures();
  const { status, message } = featureState(features, 'chat');
  const { theme } = useThemeStore();
  const isLight = theme === 'light';
  const [kllmUnavailable, setKllmUnavailable] = useState(false);
  const chatEnabled = status === 'enabled';

  // Keep the /chat shell exactly as tall as the visible viewport above the
  // mobile virtual keyboard. `100dvh` does NOT track the keyboard on iOS
  // Safari, so we sync a CSS var from window.visualViewport and lock
  // document scroll while on /chat to prevent the page from shifting the
  // shell (and its background) out of view.
  useEffect(() => {
    if (!chatEnabled || typeof window === 'undefined') return;
    const root = document.documentElement;
    const vv = window.visualViewport;

    const update = () => {
      const h = vv?.height ?? window.innerHeight;
      root.style.setProperty('--revora-chat-vh', `${Math.round(h)}px`);
    };

    update();
    vv?.addEventListener('resize', update);
    vv?.addEventListener('scroll', update);
    window.addEventListener('resize', update);
    window.addEventListener('pageshow', update);

    const prevHtmlOverflow = root.style.overflow;
    const prevBodyOverflow = document.body.style.overflow;
    root.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';

    return () => {
      vv?.removeEventListener('resize', update);
      vv?.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
      window.removeEventListener('pageshow', update);
      root.style.removeProperty('--revora-chat-vh');
      root.style.overflow = prevHtmlOverflow;
      document.body.style.overflow = prevBodyOverflow;
    };
  }, [chatEnabled]);

  if (status !== 'enabled') {
    return (
      <div className="mx-auto w-full max-w-[1200px] p-4 md:p-6 lg:p-8">
        <FeatureUnavailable
          status={status}
          message={message}
          title="Chat is unavailable"
          variant="page"
        />
      </div>
    );
  }

  return (
    <div className="relative isolate flex h-full w-full min-h-0 flex-col overflow-hidden p-0 m-0 bg-background">
      {/* Full-bleed side rays pinned to the layout viewport so the rays never end at
            the mobile keyboard edge. min-h-[100lvh] extends behind browser
            chrome/keyboard; bg-background keeps a continuous themed backdrop if
            WebGL is mid-resize. */}
      <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 min-h-[100lvh] bg-background">
        <SideRays
          rayColor1="#3B82F6"
          rayColor2="#8B5CF6"
          accentColors={
            isLight
              ? ['#FDE047', '#86EFAC', '#FDA4AF']
              : ['#FACC15', '#4ADE80', '#FB7185']
          }
          accentStrength={isLight ? 0.9 : 1.0}
          blend={isLight ? 0.45 : 0.4}
          origin="top-right"
          speed={kllmUnavailable ? 0 : 2.5}
          intensity={isLight ? 2.8 : 3.4}
          spread={2.4}
          density={6}
          sharpness={0.55}
          falloff={1.35}
          glow={isLight ? 1.1 : 1.5}
          dust={0.12}
          followMouse
          mouseInfluence={0.6}
          lightMode={isLight}
          opacity={isLight ? 0.78 : 0.95}
          maxDevicePixelRatio={2}
        />
      </div>

      <div className="relative z-10 flex h-full min-h-0 w-full flex-col">
        <ChatShell onKllmStatusChange={setKllmUnavailable} />
      </div>
    </div>
  );
}
