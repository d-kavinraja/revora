'use client';

import { useEffect, useState } from 'react';

/**
 * Mobile keyboard state for the chat layout. iOS Safari does not resize the
 * layout viewport, so `visualViewport` is the source of truth; textarea focus
 * is used as an immediate signal before the viewport actually resizes.
 */
export function useChatKeyboard(): boolean {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)');
    const vv = window.visualViewport;
    let baseline = vv?.height ?? window.innerHeight;

    const measure = () => {
      if (!mq.matches) {
        setOpen(false);
        return;
      }
      const current = vv?.height ?? window.innerHeight;
      const composing = document.activeElement instanceof HTMLTextAreaElement;
      if (current < baseline - 120) {
        setOpen(true);
        return;
      }
      if (!composing) baseline = current;
      if (current >= baseline - 80) setOpen(false);
    };

    const onFocusIn = (event: FocusEvent) => {
      if (mq.matches && event.target instanceof HTMLTextAreaElement) setOpen(true);
    };
    const onFocusOut = (event: FocusEvent) => {
      if (mq.matches && event.target instanceof HTMLTextAreaElement) {
        setOpen(false);
        baseline = vv?.height ?? window.innerHeight;
      }
    };

    measure();
    vv?.addEventListener('resize', measure);
    vv?.addEventListener('scroll', measure);
    window.addEventListener('resize', measure);
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('focusout', onFocusOut);
    return () => {
      vv?.removeEventListener('resize', measure);
      vv?.removeEventListener('scroll', measure);
      window.removeEventListener('resize', measure);
      document.removeEventListener('focusin', onFocusIn);
      document.removeEventListener('focusout', onFocusOut);
    };
  }, []);

  return open;
}
