import './auth-stage.css';

/**
 * Dotted survey canvas shared by the sign-in and OAuth callback pages.
 * Fixed behind the page, faded at the edges so the panel carries the focus.
 */
export function AuthBackdrop() {
  return <div aria-hidden="true" className="auth-backdrop" />;
}
