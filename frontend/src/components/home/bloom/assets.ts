/**
 * Watercolor asset set for the bloom landing page.
 *
 * Remote CloudFront assets are referenced with plain <img>/<video> tags
 * (no next/image), so no remotePatterns configuration is required.
 */
export const ASSETS = {
  /** Seamless cherry-blossom valley loop (petals / river / birds). */
  HERO_VIDEO:
    'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20261021_093331_5998f443-1b9c-4b62-820c-8219c73c72c4.mp4',
  /** Cherry blossom valley with a white sky — hero poster + intro backdrop. */
  HERO_POSTER:
    'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20261021_093215_b7826239-e451-4e15-b42b-d6bcf9497a32.png',
  /** Transparent cloud, puffy on the left with a wispy tail to the right. */
  CLOUD_A:
    'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20261021_093216_44218665-b15e-4566-a2d4-2676ab03609d.png',
  /** Transparent cloud, puffy on the right with a wispy tail to the left. */
  CLOUD_B:
    'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20261021_093215_0f37c0c3-f82c-485b-87dd-5a35b75a8782.png',
  /** Transparent cherry blossom trees on a flat-cut grassy base. */
  TREE:
    'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20261021_093215_95f11900-c4a0-49ad-bb2d-bb927dd594ee.png',
  /** 21:9 moonlit cherry blossom valley with a lake, deep blues. */
  NIGHT:
    'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20261021_093217_cc690198-ad8c-4127-8734-8485bd878351.png',
} as const;
