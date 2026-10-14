"use client";

import { useEffect } from "react";
import { cn } from "@/lib/utils";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { LoaderIcon } from "@/components/ui/loader-icon";

export type LoaderStageStatus = "pending" | "active" | "done" | "failed";

export interface LoaderStage {
  id: string;
  label: string;
  status: LoaderStageStatus;
  /** Live detail line rendered under the label (real values only — never fabricated). */
  detail?: string | null;
}

const PendingIcon = ({ className }: { className?: string }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
    strokeWidth={1.5}
    stroke="currentColor"
    className={cn("h-6 w-6", className)}
    aria-hidden="true"
  >
    <path d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
  </svg>
);

const DoneIcon = ({ className }: { className?: string }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="currentColor"
    className={cn("h-6 w-6", className)}
    aria-hidden="true"
  >
    <path
      fillRule="evenodd"
      d="M2.25 12c0-5.385 4.365-9.75 9.75-9.75s9.75 4.365 9.75 9.75-4.365 9.75-9.75 9.75S2.25 17.385 2.25 12Zm13.36-1.814a.75.75 0 1 0-1.22-.872l-3.236 4.53L9.53 12.22a.75.75 0 0 0-1.06 1.06l2.25 2.25a.75.75 0 0 0 1.14-.094l3.75-5.25Z"
      clipRule="evenodd"
    />
  </svg>
);

const FailedIcon = ({ className }: { className?: string }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
    strokeWidth={1.5}
    stroke="currentColor"
    className={cn("h-6 w-6", className)}
    aria-hidden="true"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="m9.75 9.75 4.5 4.5m0-4.5-4.5 4.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
    />
  </svg>
);

const CloseIcon = ({ className }: { className?: string }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
    strokeWidth={1.5}
    stroke="currentColor"
    className={cn("h-8 w-8", className)}
    aria-hidden="true"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      d="M6 18 18 6M6 6l12 12"
    />
  </svg>
);

function StageIcon({ status }: { status: LoaderStageStatus }) {
  if (status === "done") return <DoneIcon className="text-primary" />;
  if (status === "failed") return <FailedIcon className="text-destructive" />;
  if (status === "active")
    return <LoaderIcon size={24} animate className="text-primary" />;
  return <PendingIcon className="text-muted-foreground" />;
}

interface LoaderCoreProps {
  stages: LoaderStage[];
  uploadPct: number | null;
}

function LoaderCore({ stages, uploadPct }: LoaderCoreProps) {
  const reduceMotion = useReducedMotion();
  return (
    <div className="relative mx-auto flex w-full max-w-xl flex-col" role="list" aria-label="Processing stages">
      {stages.map((stage) => {
        const isActive = stage.status === "active";
        const showBar = isActive && stage.id === "upload" && uploadPct !== null;
        return (
          <motion.div
            key={stage.id}
            role="listitem"
            className="flex gap-3 text-left"
            initial={reduceMotion ? false : { opacity: 0, y: -12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
          >
            <div className="mt-1 shrink-0">
              <StageIcon status={stage.status} />
            </div>
            <div className="min-w-0 flex-1 pb-5">
              <p
                className={cn(
                  // Full token contrast on every row — hierarchy via
                  // color/weight only, never opacity dimming.
                  "text-base font-medium md:text-lg",
                  stage.status === "done" && "text-foreground",
                  isActive && "font-semibold text-foreground",
                  stage.status === "pending" && "text-muted-foreground",
                  stage.status === "failed" && "text-destructive",
                )}
              >
                {stage.label}
              </p>
              {stage.detail ? (
                <p className="mt-1 truncate text-sm tabular-nums text-muted-foreground">
                  {stage.detail}
                </p>
              ) : null}
              {showBar && uploadPct !== null ? (
                <div
                  className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-muted"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={uploadPct}
                  aria-label="Upload progress"
                >
                  <div
                    className="h-full rounded-full bg-primary transition-[width] duration-200"
                    style={{ width: `${Math.min(100, Math.max(0, uploadPct))}%` }}
                  />
                </div>
              ) : null}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}

export interface MultiStepLoaderProps {
  open: boolean;
  stages: LoaderStage[];
  title: string;
  subtitle?: string | null;
  /** Real XHR upload percent (0-100). Null while not uploading. */
  uploadPct?: number | null;
  /** Seconds since the run started. Ticked by the parent — display only. */
  elapsedS?: number;
  onCancel?: () => void;
}

export function MultiStepLoader({
  open,
  stages,
  title,
  subtitle,
  uploadPct = null,
  elapsedS = 0,
  onCancel,
}: MultiStepLoaderProps) {
  const reduceMotion = useReducedMotion();

  // Lock body scroll while the blocking overlay is open.
  useEffect(() => {
    if (!open || typeof document === "undefined") return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open ]);

  // Escape cancels the in-flight request.
  useEffect(() => {
    if (!open || !onCancel) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={reduceMotion ? { duration: 0 } : { duration: 0.2 }}
          className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-background/60 px-4 backdrop-blur-2xl"
          role="dialog"
          aria-modal="true"
          aria-label={title}
        >
          {onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              aria-label="Cancel inference"
              autoFocus
              className="fixed top-4 right-4 z-10 rounded-full text-muted-foreground transition-colors hover:text-foreground"
            >
              <CloseIcon />
            </button>
          ) : null}

          <div className="relative mt-32 w-full md:mt-40" role="status" aria-live="polite">
            <div className="mx-auto mb-8 max-w-xl">
              <p className="text-xl font-semibold text-foreground md:text-2xl">{title}</p>
              <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
                {subtitle ? <span className="truncate">{subtitle}</span> : null}
                <span aria-hidden="true">·</span>
                <span className="shrink-0 tabular-nums">Elapsed {elapsedS}s</span>
              </div>
            </div>
            <LoaderCore stages={stages} uploadPct={uploadPct} />
          </div>

          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 bottom-0 h-full bg-gradient-to-t from-background via-background/60 to-transparent [mask-image:radial-gradient(900px_at_center,transparent_30%,black)]"
          />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
