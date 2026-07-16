'use client';

import { useThemeStore } from '@/store/useThemeStore';
import { SunIcon, MoonIcon } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggleTheme } = useThemeStore();

  return (
    <button
      onClick={toggleTheme}
      className={`relative p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-white/[0.06] hover:ring-1 hover:ring-border transition-all duration-150 cursor-pointer ${className ?? ''}`}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
    >
      <AnimatePresence mode="wait" initial={false}>
        {theme === 'dark' ? (
          <motion.span
            key="sun"
            initial={{ rotate: -90, scale: 0 }}
            animate={{ rotate: 0, scale: 1 }}
            exit={{ rotate: 90, scale: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="block"
          >
            <SunIcon size={16} className="text-amber-400" />
          </motion.span>
        ) : (
          <motion.span
            key="moon"
            initial={{ rotate: 90, scale: 0 }}
            animate={{ rotate: 0, scale: 1 }}
            exit={{ rotate: -90, scale: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="block"
          >
            <MoonIcon size={16} className="text-slate-600" />
          </motion.span>
        )}
      </AnimatePresence>
    </button>
  );
}

