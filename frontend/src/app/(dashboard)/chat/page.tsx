'use client';

import SideRays from '@/components/ui/SideRays';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { useChatModes } from '@/lib/use-chat-modes';
import { useThemeStore } from '@/store/useThemeStore';

import { useEffect, useState, useSyncExternalStore } from 'react';
import { ChatShell } from './_components/chat-shell';
import { PersistentChatShell } from './_components/persistent-chat-shell';

// Stable snapshots for the hydration gate. React uses the server snapshot while
// hydrating and switches to the client snapshot once the tree is attached.
const subscribeMounted = () => () => {};
const getClientMounted = () => true;
const getServerMounted = () => false;

export default function ChatPage() {
  const modesQuery = useChatModes();
  const modes = modesQuery.data;
  const [selectedMode, setSelectedMode] = useState<'temporary' | 'persistent' | null>(null);
  // The query cache can already hold data on the first client render (cached
  // RSC payload or a client navigation back to /chat), while SSR always renders
  // the pending branch. useSyncExternalStore gives hydration the server snapshot
  // (false) for the first render and the client snapshot (true) immediately
  // afterwards, so both trees start from the same deterministic loading markup.
  const mounted = useSyncExternalStore(subscribeMounted, getClientMounted, getServerMounted);
  const { theme } = useThemeStore();
  const isLight = theme === 'light';
  const [kllmUnavailable, setKllmUnavailable] = useState(false);
  const defaultMode = modes?.persistent_enabled
    ? 'persistent'
    : modes?.temporary_enabled
      ? 'temporary'
      : 'persistent';
  const activeMode = selectedMode === 'temporary' && modes?.temporary_enabled
    ? 'temporary'
    : selectedMode === 'persistent'
      ? 'persistent'
      : defaultMode;
  const modeAvailable = activeMode === 'temporary'
    ? modes?.temporary_enabled === true
    : modes?.persistent_enabled === true;
  const chatEnabled = !!modes && (modeAvailable || activeMode === 'persistent');

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

  if (!mounted || modesQuery.isPending || modesQuery.isError || !modes) {
    return (
      <div className="mx-auto w-full max-w-[1200px] p-4 md:p-6 lg:p-8">
        <FeatureUnavailable
          status={!mounted || modesQuery.isPending ? 'under_testing' : 'disabled'}
          message={modesQuery.isError ? 'Chat mode settings are unavailable. Please try again later.' : 'Loading Chat availability…'}
          title={modesQuery.isError ? 'Chat is unavailable' : 'Loading Chat'}
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
        <div className={`min-h-0 flex-1 ${activeMode === 'temporary' ? '' : 'hidden'}`}>
          <ChatShell
            onKllmStatusChange={setKllmUnavailable}
            activeMode="temporary"
            isActive={activeMode === 'temporary'}
            temporaryEnabled={modes.temporary_enabled}
            persistentEnabled={modes.persistent_enabled}
            onModeChange={setSelectedMode}
          />
        </div>
        <div className={`min-h-0 flex-1 ${activeMode === 'persistent' ? '' : 'hidden'}`}>
          <PersistentChatShell
            enabled={modes.persistent_enabled}
            activeMode="persistent"
            isActive={activeMode === 'persistent'}
            temporaryEnabled={modes.temporary_enabled}
            persistentEnabled={modes.persistent_enabled}
            onModeChange={setSelectedMode}
            onKllmStatusChange={setKllmUnavailable}
          />
        </div>
      </div>
    </div>
  );
}
