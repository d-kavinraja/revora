'use client';

import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { Button } from '@/components/ui/button';

export default function RegisterPage() {
  const router = useRouter();

  return (
    <div className="min-h-screen flex items-center justify-center bg-black relative overflow-hidden">
      <div className="absolute top-[20%] right-[30%] w-[40%] h-[40%] bg-purple-600/20 blur-[120px] rounded-full pointer-events-none" />
      
      <motion.div 
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="w-full max-w-md p-8 bg-zinc-950/50 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl z-10"
      >
        <div className="text-center mb-8">
          <div className="w-12 h-12 mx-auto rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center font-bold text-2xl mb-4 shadow-[0_0_15px_rgba(59,130,246,0.5)] text-white">
            R
          </div>
          <h2 className="text-2xl font-bold text-white">Get Started</h2>
          <p className="text-zinc-400 mt-2">Create your Revora account</p>
        </div>

        {/* Development Callout Info */}
        <div className="p-6 rounded-xl border border-yellow-500/25 bg-yellow-500/5 text-center shadow-lg mb-6">
          <p className="text-sm font-medium text-yellow-300 leading-relaxed">
            🚧 Account registration is currently disabled. Please sign in with GitHub or contact the developer team.
          </p>
        </div>

        <Button 
          type="button" 
          onClick={() => router.push('/login')}
          className="w-full h-12 bg-white text-black hover:bg-gray-200 text-base font-semibold shadow-[0_0_15px_rgba(255,255,255,0.2)] transition-all duration-200 cursor-pointer"
        >
          Back to Sign In
        </Button>
      </motion.div>
    </div>
  );
}
