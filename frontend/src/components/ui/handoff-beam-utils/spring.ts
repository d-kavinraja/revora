export interface SpringConfig {
  stiffness: number;
  damping: number;
  mass: number;
}

export interface SpringState {
  x: number;
  v: number;
}

export function stepSpring(
  state: SpringState,
  target: number,
  config: SpringConfig,
  dt: number,
) {
  if (dt <= 0) return;

  const mass = Math.max(0.001, config.mass);
  const stiffness = config.stiffness;
  const damping = config.damping;

  // Semi-implicit Euler is stable enough for this small visual spring.
  const displacement = state.x - target;
  const acceleration = (-stiffness * displacement - damping * state.v) / mass;
  state.v += acceleration * dt;
  state.x += state.v * dt;

  if (Math.abs(state.x - target) < 0.0001 && Math.abs(state.v) < 0.0001) {
    state.x = target;
    state.v = 0;
  }
}
