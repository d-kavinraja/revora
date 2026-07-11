'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { Button } from '@/components/ui/button';

export default function LoginPage() {
  const router = useRouter();

  const handleGitHubLogin = () => {
    const clientId = process.env.NEXT_PUBLIC_GITHUB_CLIENT_ID || 'Iv23lix4UrdcNq2hoWol';
    const redirectUri = `${window.location.origin}/auth/callback`;
    window.location.href = `https://github.com/login/oauth/authorize?client_id=${clientId}&redirect_uri=${redirectUri}&scope=read:user,user:email`;
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-black relative overflow-hidden">
      <div className="absolute top-[20%] left-[30%] w-[40%] h-[40%] bg-blue-600/20 blur-[120px] rounded-full pointer-events-none" />
      
      <motion.div 
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="w-full max-w-md p-8 bg-zinc-950/50 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl z-10"
      >
        <div className="text-center mb-8">
          <div className="w-12 h-12 mx-auto rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center font-bold text-2xl mb-4 shadow-[0_0_15px_rgba(59,130,246,0.5)] text-white">
            R
          </div>
          <h2 className="text-2xl font-bold text-white">Welcome back</h2>
          <p className="text-zinc-400 mt-2">Sign in to your Revora account</p>
        </div>

        {/* GitHub Login Button */}
        <Button 
          type="button" 
          onClick={handleGitHubLogin}
          className="w-full h-12 bg-[#24292e] text-white hover:bg-[#2c3238] hover:text-white border border-white/10 rounded-lg flex items-center justify-center gap-2.5 font-semibold text-sm mb-8 cursor-pointer shadow-lg transition-all duration-200"
        >
          <svg className="w-5 h-5 fill-current" viewBox="0 0 24 24">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
          </svg>
          Sign in with GitHub
        </Button>

        {/* Development Callout Info */}
        <div className="p-4 rounded-xl border border-yellow-500/25 bg-yellow-500/5 text-center shadow-lg">
          <p className="text-sm font-medium text-yellow-300 leading-relaxed">
            🚧 Username and password login is currently in development. Please contact the developer team.
          </p>
        </div>
      </motion.div>
    </div>
  );
}
