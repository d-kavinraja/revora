'use client';

import SideRays from '@/components/ui/SideRays';
import { FeatureUnavailable } from '@/components/shared/feature-unavailable';
import { featureState, usePlatformFeatures } from '@/lib/use-platform-features';
import { useThemeStore } from '@/store/useThemeStore';

import { ChatShell } from './_components/chat-shell';

export default function ChatPage() {
  const { data: features } = usePlatformFeatures();
  const { status, message } = featureState(features, 'chat');
  const { theme } = useThemeStore();
  const isLight = theme === 'light';

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
    <div className="relative isolate flex h-full w-full min-h-0 flex-col overflow-hidden p-0 m-0">
      {/* Full-bleed side rays behind the chat UI, fixed to the chat viewport. */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-0">
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
          speed={2.5}
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
        <ChatShell />
      </div>
    </div>
  );
}
