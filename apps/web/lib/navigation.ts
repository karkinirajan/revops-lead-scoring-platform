/** The sign-in page, returning to `returnTo` afterwards. */
export function loginUrl(returnTo: string): string {
  return `/login?next=${encodeURIComponent(returnTo)}`;
}

/** Leave for the sign-in page with a full page load, so nothing from the old session (client state, cached pages) survives. */
export function goToLogin(): void {
  const target = loginUrl(window.location.pathname + window.location.search);
  window.location.assign(target);
}
