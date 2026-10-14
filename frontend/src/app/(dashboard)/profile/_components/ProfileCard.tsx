'use client';

import { useState } from 'react';
import { MailIcon } from 'lucide-react';
import Aurora from '@/components/ui/Aurora';
import { useThemeStore } from '@/store/useThemeStore';
import type { User } from '@/store/useAuthStore';

interface ProfileCardProps {
  user: User;
}

/** GitHub mark, inlined like header.tsx (no extra dependency). */
const GithubMarkIcon = ({ size = 20, className = '' }: { size?: number; className?: string }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}><path d="M12 .5C5.73.5.9 5.33.9 11.6c0 4.9 3.17 9.05 7.58 10.53.55.1.76-.24.76-.53v-1.87c-3.08.68-3.73-1.29-3.73-1.29-.51-1.29-1.24-1.63-1.24-1.63-1.01-.69.08-.68.08-.68 1.12.08 1.71 1.15 1.71 1.15 1 1.72 2.63 1.22 3.27.94.1-.73.39-1.24.71-1.52-2.46-.28-5.05-1.23-5.05-5.48 0-1.21.43-2.21 1.14-2.99-.11-.28-.49-1.41.11-2.94 0 0 .93-.3 3.05 1.15a10.5 10.5 0 0 1 5.55 0c2.12-1.45 3.05-1.15 3.05-1.15.6 1.53.22 2.66.11 2.94.71.78 1.14 1.78 1.14 2.99 0 4.26-2.6 5.19-5.07 5.47.4.35.76 1.03.76 2.08v3.09c0 .3.2.65.77.53A11.1 11.1 0 0 0 23.1 11.6C23.1 5.33 18.27.5 12 .5Z" /></svg>
);

/**
 * Full-width landscape identity card — reference-image layout:
 * avatar on the left, name/role/email/GitHub
 * arranged horizontally on desktop, stacked on mobile.
 *
 * The GitHub username renders ONLY when it actually exists on the user
 * object. Revora's backend currently does NOT send `github_username` to the
 * frontend (stored server-side after OAuth but omitted from auth payloads),
 * so the GitHub block is hidden today — conditional, never fabricated.
 */
export function ProfileCard({ user }: ProfileCardProps) {
  const { theme } = useThemeStore();
  const isLight = theme === 'light';
  const githubUsername = typeof user.github_username === 'string' ? user.github_username.trim() : '';
  const githubUrl = githubUsername ? `https://github.com/${githubUsername}` : '';
  const displayName = user.name?.trim() || 'User';
  const [brokenAvatarSrc, setBrokenAvatarSrc] = useState<string | null>(null);
  // A broken avatar URL degrades to the initial without a retry loop: the
  // failed src is remembered, while any new user/image is attempted fresh.
  // Render-derived (no effect), so no cascading renders.
  const avatarSrc =
    user.image && user.image !== brokenAvatarSrc ? user.image : null;

  return (
    <section aria-label="Profile" className="relative rounded-2xl border border-border bg-surface-1 shadow-sm overflow-hidden">
      {/* Aurora background — decorative layer confined to this card (clipped by
          overflow-hidden + rounded-2xl). pointer-events-none so it never
          intercepts card interactions; the component's own cursor reach still
          works via its window-level listeners. The relative content row below
          paints above it by DOM order. */}
      <div aria-hidden="true" className="absolute inset-0 z-0 pointer-events-none">
        <Aurora
          colorStops={
            isLight
              ? ['#ef4444', '#f59e0b', '#16a34a', '#2563eb', '#7c3aed']
              : ['#ef4444', '#f59e0b', '#22c55e', '#3b82f6', '#a855f7']
          }
          height={0.85}
          amplitude={1}
          blend={0.6}
          speed={1}
          scale={1.15}
          glow={0.7}
          brightness={isLight ? 1.05 : 1.1}
          layers={3}
          direction="top"
          mouseInteraction
          intro
          lightMode={isLight}
          opacity={isLight ? 0.62 : 0.5}
        />
      </div>

      {/* Content row — horizontal on desktop */}
      <div className="relative z-10 p-5 md:p-6 flex flex-col sm:flex-row sm:items-center gap-4 md:gap-5">
        {/* Avatar */}
        <div className="shrink-0">
          {avatarSrc ? (
            // Plain <img> like the sidebar avatar — the GitHub avatar host is not
            // whitelisted in next.config images.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={avatarSrc}
              alt={displayName}
              onError={() => setBrokenAvatarSrc(avatarSrc)}
              className="w-16 h-16 md:w-20 md:h-20 rounded-full object-cover border-4 border-surface-1 shadow-md bg-surface-2"
            />
          ) : (
            <div
              aria-hidden="true"
              className="w-16 h-16 md:w-20 md:h-20 rounded-full bg-gradient-to-br from-brand to-brand-hover flex items-center justify-center uppercase font-bold text-2xl md:text-3xl text-white border-4 border-surface-1 shadow-md"
            >
              {displayName.charAt(0)}
            </div>
          )}
        </div>

        {/* Identity block */}
        <div className="flex-1 min-w-0">
          {/* Name + role */}
          <div className="flex flex-wrap items-center gap-2.5 min-w-0">
            <h2 className="text-xl md:text-2xl font-heading font-bold tracking-tight text-foreground break-words min-w-0">
              {displayName}
            </h2>
            {user.role && (
              <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-brand text-brand-foreground border border-brand capitalize shrink-0">
                {user.role}
              </span>
            )}
          </div>

          {/* Email | GitHub — horizontal on desktop, stacked on mobile.
              GitHub renders only when the username actually exists in app
              state (see note above). */}
          <div className="mt-3 flex flex-col sm:flex-row sm:items-stretch gap-3 sm:gap-0 min-w-0">
            <span className="flex items-center gap-2.5 min-w-0 sm:pr-5">
              <span className="shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-surface-1/90 border border-border text-foreground/80">
                <MailIcon size={14} aria-hidden="true" />
              </span>
              <span className="min-w-0">
                <span className="block text-[10px] font-semibold uppercase tracking-wider text-foreground/70 leading-tight">
                  Email
                </span>
                <span className="block text-sm font-medium text-foreground/90 truncate">{user.email}</span>
              </span>
            </span>

            {githubUsername && (
              <>
                <span aria-hidden="true" className="hidden sm:block w-px bg-border shrink-0" />
                <span className="flex items-center gap-2.5 min-w-0 sm:pl-5">
                  <span className="shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-surface-1/90 border border-border text-foreground/80">
                    <GithubMarkIcon size={15} />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[10px] font-semibold uppercase tracking-wider text-foreground/70 leading-tight">
                      GitHub
                    </span>
                    {githubUrl ? (
                      <a
                        href={githubUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block text-sm font-semibold text-foreground hover:text-brand transition-colors truncate"
                        aria-label={`GitHub profile: ${githubUsername}`}
                      >
                        @{githubUsername}
                      </a>
                    ) : (
                      <span className="block text-sm font-semibold text-foreground truncate">@{githubUsername}</span>
                    )}
                  </span>
                </span>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
