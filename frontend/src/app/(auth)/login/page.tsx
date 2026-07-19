'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { SoftAurora } from '@/components/ui/SoftAurora';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { cn } from "@/lib/utils";
import { api } from '@/lib/api';
import { useToast } from '@/components/ui/toaster';
import { InfoIcon } from '@animateicons/react/lucide';
import Image from 'next/image';

import { useThemeStore } from '@/store/useThemeStore';

export default function LoginPage() {
  const router = useRouter();
  const [loadingConfig, setLoadingConfig] = useState(false);
  const { toast } = useToast();
  const { theme } = useThemeStore();
  const isLight = theme === 'light';

  const handleGitHubLogin = async () => {
    setLoadingConfig(true);
    try {
      const config = await api.getAuthConfig();
      const clientId = config.github_client_id;
      if (!clientId) {
        toast({
          title: "GitHub Client ID is not configured on the backend.",
          type: "error"
        });
        setLoadingConfig(false);
        return;
      }
      const redirectUri = `${window.location.origin}/auth/callback`;
      window.location.href = `https://github.com/login/oauth/authorize?client_id=${clientId}&redirect_uri=${redirectUri}&scope=read:user,user:email`;
    } catch (err) {
      console.error('Failed to get auth config', err);
      toast({
        title: "Failed to connect to the backend authorization service.",
        type: "error"
      });
      setLoadingConfig(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background relative overflow-hidden">
      {/* Background gradients and SoftAurora */}
      <div className="absolute inset-0 pointer-events-none z-0">
        <SoftAurora
          speed={0.6}
          scale={1.5}
          brightness={isLight ? 0.7 : 1.0}
          color1={isLight ? "#2563eb" : "#f7f7f7"}
          color2={isLight ? "#7c3aed" : "#e100ff"}
          noiseFrequency={2.5}
          noiseAmplitude={1.0}
          bandHeight={0.5}
          bandSpread={1.0}
          octaveDecay={0.1}
          layerOffset={0}
          colorSpeed={1.0}
          enableMouseInteraction={true}
          mouseInfluence={0.25}
        />
      </div>
      <div className="absolute top-[15%] left-[25%] w-[35%] h-[35%] bg-brand/15 blur-[120px] rounded-full pointer-events-none z-0" />
      <div className="absolute bottom-[15%] right-[25%] w-[30%] h-[30%] bg-purple-600/10 blur-[120px] rounded-full pointer-events-none z-0" />

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="w-full max-w-md p-8 bg-white/10 dark:bg-black/20 backdrop-blur-2xl border border-white/30 dark:border-white/10 rounded-2xl shadow-[0_8px_32px_0_rgba(31,38,135,0.1)] dark:shadow-[0_8px_32px_0_rgba(0,0,0,0.5)] z-10 ring-1 ring-white/20 dark:ring-white/5"
      >
        <div className="text-center mb-8">
          <Image
            src="/revora-logo.png"
            alt="Revora Logo"
            width={48}
            height={48}
            className="mx-auto rounded-xl object-contain mb-4 shadow-[0_0_20px_rgba(99,102,241,0.35)]"
          />
          <h2 className="text-2xl font-bold text-foreground drop-shadow-md">Welcome back</h2>
          <p className="text-foreground/80 mt-2 font-medium drop-shadow-sm">Sign in to your Revora account</p>
        </div>

        <button
          type="button"
          onClick={handleGitHubLogin}
          disabled={loadingConfig}
          className="w-full h-12 bg-[#24292e] text-white hover:bg-[#2c3238] border border-white/10 rounded-lg flex items-center justify-center gap-2.5 font-semibold text-sm cursor-pointer shadow-lg transition-all duration-150 disabled:opacity-50"
        >
          {loadingConfig ? (
            <LoaderIcon size={18} animate />
          ) : (
            <svg className="w-5 h-5 fill-current" viewBox="0 0 24 24">
              <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
            </svg>
          )}
          Sign in with GitHub
        </button>

        <div className="overflow-hidden w-full mt-6 border-t border-border pt-4 relative h-8 flex items-center">
          <motion.div
            initial={{ x: '100%' }}
            animate={{ x: '-100%' }}
            transition={{
              repeat: Infinity,
              ease: 'linear',
              duration: 8,
            }}
            className="absolute whitespace-nowrap text-xs text-foreground/70 font-medium flex items-center gap-1.5 drop-shadow-sm"
          >
            <InfoIcon size={14} className="text-info" />
            Notice: Username and password login coming soon.
          </motion.div>
        </div>
      </motion.div>
    </div>
  );
}
