import { ImageResponse } from 'next/og';
import { SOCIAL_IMAGE, getSiteHost } from '@/lib/site';

/**
 * Shared branded social preview (1200x630).
 *
 * Rendered with `next/og` so the image is generated from the same source of truth as
 * the rest of the metadata - no binary asset to keep in sync. The default font is used
 * on purpose: it keeps image generation free of network requests and build-time
 * dependencies, and the brand is carried by the layout, colour tokens (indigo
 * `--brand` + the blue/cyan logo gradient) and copy instead.
 */

export const OG_IMAGE_SIZE = { width: SOCIAL_IMAGE.width, height: SOCIAL_IMAGE.height };

export const OG_IMAGE_ALT = SOCIAL_IMAGE.alt;

export function renderBrandOgImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: '64px 72px',
          backgroundColor: '#0b0b12',
          backgroundImage:
            'radial-gradient(900px 520px at 6% -14%, rgba(99,102,241,0.55) 0%, rgba(11,11,18,0) 70%), radial-gradient(780px 460px at 104% 112%, rgba(34,211,238,0.32) 0%, rgba(11,11,18,0) 70%)',
          color: '#f8fafc',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 76,
              height: 76,
              marginRight: 24,
              borderRadius: 22,
              backgroundImage:
                'linear-gradient(135deg, #8b5cf6 0%, #4f46e5 48%, #22d3ee 100%)',
              fontSize: 46,
              fontWeight: 700,
              color: '#ffffff',
            }}
          >
            R
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <div style={{ fontSize: 30, fontWeight: 700, letterSpacing: '3px' }}>
              REVORA SYSTEM
            </div>
            <div style={{ fontSize: 22, color: '#a5b4fc', marginTop: 6 }}>
              Open-source AI code review for GitHub
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontSize: 92, fontWeight: 700, lineHeight: 1.05, letterSpacing: '-2px' }}>
            AI Code Review
          </div>
          <div style={{ fontSize: 40, fontWeight: 600, color: '#c7d2fe', marginTop: 16 }}>
            Repository-Aware · Reads your whole codebase
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: 24,
            color: '#94a3b8',
          }}
        >
          <div style={{ display: 'flex' }}>
            Security, performance and code-quality findings you can verify
          </div>
          <div style={{ display: 'flex' }}>{getSiteHost()}</div>
        </div>
      </div>
    ),
    { ...OG_IMAGE_SIZE }
  );
}
