'use client';

import { motion } from "framer-motion";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { GithubIcon } from "@animateicons/react/lucide";
import { useRef } from "react";

export default function LandingPage() {
  const githubIconRef = useRef<any>(null);

  return (
    <div className="flex min-h-screen flex-col bg-black text-white relative overflow-hidden">
      {/* Background gradients */}
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-blue-600/30 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-purple-600/30 blur-[120px] rounded-full pointer-events-none" />
      
      <header className="flex items-center justify-between p-6 z-10 border-b border-white/10 bg-black/50 backdrop-blur-md sticky top-0">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center font-bold text-lg shadow-[0_0_15px_rgba(59,130,246,0.5)]">
            R
          </div>
          <span className="font-bold text-xl tracking-tight">Revora</span>
        </div>
        <nav className="flex gap-4">
          <Link href="/login">
            <Button variant="ghost" className="text-white hover:text-white hover:bg-white/10">Sign In</Button>
          </Link>
          <Link href="/register">
            <Button className="bg-white text-black hover:bg-gray-200 shadow-[0_0_15px_rgba(255,255,255,0.3)]">Get Started</Button>
          </Link>
        </nav>
      </header>

      <main className="flex-1 flex flex-col items-center justify-center p-6 text-center z-10">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
          className="max-w-4xl space-y-8"
        >
          <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight leading-tight">
            The Ultimate <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-500">AI Code Reviewer</span>
          </h1>
          <p className="text-xl md:text-2xl text-gray-400 max-w-2xl mx-auto font-light">
            Supercharge your engineering team with context-aware, repository-wide intelligence. Catch bugs, secure endpoints, and optimize performance before merging.
          </p>
          <div className="flex items-center justify-center gap-6 pt-4">
            <Link href="/login">
              <Button
                size="lg"
                onMouseEnter={() => githubIconRef.current?.startAnimation()}
                onMouseLeave={() => githubIconRef.current?.stopAnimation()}
                className="h-14 px-8 text-lg bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white shadow-[0_0_30px_rgba(147,51,234,0.4)] border-0 transition-all hover:scale-105 gap-2"
              >
                Install GitHub App
                <GithubIcon ref={githubIconRef} size={20} isAnimated={false} />
              </Button>
            </Link>
          </div>
        </motion.div>
      </main>
    </div>
  );
}
