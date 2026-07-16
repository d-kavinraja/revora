'use client';

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import { XIcon, CircleCheckIcon, TriangleAlertIcon, InfoIcon } from '@animateicons/react/lucide';
import { motion, AnimatePresence } from 'framer-motion';

export type ToastType = 'success' | 'error' | 'info' | 'loading';

export interface Toast {
  id: string;
  title: string;
  description?: string;
  type: ToastType;
}

interface ToastContextType {
  toasts: Toast[];
  toast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToasterProvider');
  }
  return context;
}

export function ToasterProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((newToast: Omit<Toast, 'id'>) => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { ...newToast, id }]);
    
    if (newToast.type !== 'loading') {
      setTimeout(() => {
        removeToast(id);
      }, 5000);
    }
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toasts, toast, removeToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: 20, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 20, scale: 0.95 }}
              className="pointer-events-auto flex items-start gap-3 bg-surface-1 border border-border p-4 rounded-xl shadow-lg relative overflow-hidden group"
            >
              <div className="shrink-0 mt-0.5">
                {t.type === 'success' && <CircleCheckIcon size={18} className="text-success" />}
                {t.type === 'error' && <TriangleAlertIcon size={18} className="text-error" />}
                {t.type === 'info' && <InfoIcon size={18} className="text-info" />}
                {t.type === 'loading' && (
                  <span
                    className="animate-spin"
                    style={{
                      display: 'inline-block',
                      width: 18,
                      height: 18,
                      borderRadius: '50%',
                      borderWidth: 2.5,
                      borderStyle: 'solid',
                      borderColor: 'rgba(99,102,241,0.25)',
                      borderTopColor: 'oklch(0.62 0.2 265)',
                      flexShrink: 0,
                    }}
                  />
                )}
              </div>
              <div className="flex-1 min-w-0 pr-6">
                <p className="text-sm font-semibold text-foreground">{t.title}</p>
                {t.description && <p className="text-xs text-muted-foreground mt-1">{t.description}</p>}
              </div>
              <button
                onClick={() => removeToast(t.id)}
                className="absolute top-3 right-3 p-1 rounded-md text-muted-foreground/50 hover:text-foreground hover:bg-white/[0.05] transition-colors"
              >
                <XIcon size={14} />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
