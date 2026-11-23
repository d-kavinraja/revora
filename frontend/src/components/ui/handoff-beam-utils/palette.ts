export type BjorkTone = "light" | "dark";

export const BJORK_PALETTE: Record<
  BjorkTone,
  {
    accent: string;
    text: string;
  }
> = {
  dark: {
    accent: "#ec5c13",
    text: "#ededed",
  },
  light: {
    accent: "#dc4a0c",
    text: "#1b1b1b",
  },
};
