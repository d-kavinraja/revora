import { OG_IMAGE_ALT, OG_IMAGE_SIZE, renderBrandOgImage } from '@/components/seo/og-image';

export const alt = OG_IMAGE_ALT;
export const size = OG_IMAGE_SIZE;
export const contentType = 'image/png';

/**
 * The same branded 1200x630 artwork for X/Twitter cards, generated from the same
 * source so the two previews can never drift apart.
 */
export default function TwitterImage() {
  return renderBrandOgImage();
}
