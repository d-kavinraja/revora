function hash1D(n: number): number {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453123;
  return x - Math.floor(x);
}

function smoothstep(t: number): number {
  return t * t * (3 - 2 * t);
}

export function valueNoise1D(seed: number): (x: number) => number {
  return (x: number) => {
    const i = Math.floor(x);
    const f = x - i;
    const a = hash1D(i + seed * 1013);
    const b = hash1D(i + 1 + seed * 1013);
    return a + (b - a) * smoothstep(f);
  };
}
