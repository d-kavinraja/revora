import { MailIcon } from 'lucide-react';
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
 * banner backdrop, avatar on the left, name/role/email/GitHub
 * arranged horizontally on desktop, stacked on mobile.
 *
 * The GitHub username renders ONLY when it actually exists on the user
 * object. Revora's backend currently does NOT send `github_username` to the
 * frontend (stored server-side after OAuth but omitted from auth payloads),
 * so the GitHub block is hidden today — conditional, never fabricated.
 */
export function ProfileCard({ user }: ProfileCardProps) {
  const githubUsername = typeof user.github_username === 'string' ? user.github_username.trim() : '';
  const githubUrl = githubUsername ? `https://github.com/${githubUsername}` : '';
  const displayName = user.name?.trim() || 'User';

  return (
    <section aria-label="Profile" className="relative rounded-2xl border border-border bg-surface-1 shadow-sm overflow-hidden">
      {/* Banner backdrop — soft sky→indigo→purple wash with subtle abstract shapes */}
      <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-r from-sky-500/15 via-indigo-500/10 to-purple-500/15" />
      <div aria-hidden="true" className="absolute -top-16 -right-10 w-64 h-64 rounded-full bg-purple-500/10 blur-3xl" />
      <div aria-hidden="true" className="absolute -bottom-20 left-1/3 w-72 h-72 rounded-full bg-sky-500/10 blur-3xl" />

      {/* Content row — horizontal on desktop */}
      <div className="relative p-5 md:p-6 flex flex-col sm:flex-row sm:items-center gap-4 md:gap-5">
        {/* Avatar */}
        <div className="shrink-0">
          {user.image ? (
            // Plain <img> like the sidebar avatar — the GitHub avatar host is not
            // whitelisted in next.config images.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={user.image}
              alt={displayName}
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
              <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-brand/15 text-brand border border-brand/25 capitalize shrink-0">
                {user.role}
              </span>
            )}
          </div>

          {/* Email | GitHub — horizontal on desktop, stacked on mobile.
              GitHub renders only when the username actually exists in app
              state (see note above). */}
          <div className="mt-3 flex flex-col sm:flex-row sm:items-stretch gap-3 sm:gap-0 min-w-0">
            <span className="flex items-center gap-2.5 min-w-0 sm:pr-5">
              <span className="shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-surface-1/80 border border-border text-muted-foreground">
                <MailIcon size={14} aria-hidden="true" />
              </span>
              <span className="min-w-0">
                <span className="block text-[10px] font-semibold uppercase tracking-wider text-muted-foreground leading-tight">
                  Email
                </span>
                <span className="block text-sm font-medium text-foreground/90 truncate">{user.email}</span>
              </span>
            </span>

            {githubUsername && (
              <>
                <span aria-hidden="true" className="hidden sm:block w-px bg-border shrink-0" />
                <span className="flex items-center gap-2.5 min-w-0 sm:pl-5">
                  <span className="shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-surface-1/80 border border-border text-foreground/80">
                    <GithubMarkIcon size={15} />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[10px] font-semibold uppercase tracking-wider text-muted-foreground leading-tight">
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
