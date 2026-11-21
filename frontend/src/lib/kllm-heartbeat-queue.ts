/**
 * Serializes advisory presence heartbeats so a newer desired state is always
 * sent after an older one. Used by the kLLM active-session hook.
 *
 * This is deliberately a small, transport-independent state machine: the
 * caller owns timers, browser events and the actual HTTP request.
 */

export type PresenceHeartbeatSender = (active: boolean) => Promise<void>;

export interface PresenceHeartbeatQueue {
  /** Queue the newest desired presence state. Latest signal wins. */
  request(active: boolean): void;
  /** Stop the queue; no further heartbeats are sent. */
  stop(): void;
  readonly inFlight: boolean;
  readonly pending: boolean | null;
  readonly desired: boolean | null;
}

export function createPresenceHeartbeatQueue(
  send: PresenceHeartbeatSender,
): PresenceHeartbeatQueue {
  let inFlight = false;
  let queued: boolean | null = null;
  let desired: boolean | null = null;
  let stopped = false;
  let pump: Promise<void> | null = null;

  const drain = async (): Promise<void> => {
    while (!stopped && queued !== null) {
      const next = queued;
      queued = null;
      inFlight = true;
      try {
        await send(next);
      } catch {
        // Presence is advisory; server-side TTL is the backstop.
      } finally {
        inFlight = false;
      }
    }
  };

  const run = async (): Promise<void> => {
    if (stopped || inFlight || pump) return;
    pump = drain().finally(() => {
      pump = null;
    });
    await pump;
  };

  return {
    request(active: boolean): void {
      if (stopped) return;
      desired = active;
      // Replacing (not appending) is intentional: an active signal that was
      // already in flight must never be followed by a stale queued active
      // after the user has hidden the tab.
      queued = active;
      void run();
    },
    stop(): void {
      stopped = true;
      queued = null;
    },
    get inFlight(): boolean {
      return inFlight;
    },
    get pending(): boolean | null {
      return queued;
    },
    get desired(): boolean | null {
      return desired;
    },
  };
}
