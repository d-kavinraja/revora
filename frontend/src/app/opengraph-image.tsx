import { OG_IMAGE_ALT, OG_IMAGE_SIZE, renderBrandOgImage } from '@/components/seo/og-image';

export const alt = OG_IMAGE_ALT;
export const size = OG_IMAGE_SIZE;
export const contentType = 'image/png';

/** Branded Open Graph image (1200x630), generated from the Revora source of truth. */
export default function OpengraphImage() {
  return renderBrandOgImage();
}
