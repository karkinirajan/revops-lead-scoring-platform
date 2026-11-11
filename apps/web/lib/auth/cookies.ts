import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/config";
import type { TokenPair } from "./tokens";

const REFRESH_DAYS = 7; // the API's JWT_REFRESH_TOKEN_EXPIRE_DAYS default; the API is what really enforces it

export type CookieSpec = {
  name: string;
  value: string;
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: "/";
  maxAge: number;
};

/** Secure unless the deployment says it serves plain http (COOKIE_SECURE=false): a Secure cookie is dropped by browsers on http://, other than localhost. */
function secure(): boolean {
  if (process.env.COOKIE_SECURE === "false") return false;
  return process.env.NODE_ENV === "production";
}

function base(name: string, value: string, maxAge: number): CookieSpec {
  return { name, value, httpOnly: true, secure: secure(), sameSite: "lax", path: "/", maxAge };
}

/** The two session cookies for a token pair. httpOnly, so no script on the page (and so no XSS) can read a token. */
export function sessionCookies(tokens: TokenPair): CookieSpec[] {
  return [
    base(ACCESS_COOKIE, tokens.access_token, tokens.expires_in),
    base(REFRESH_COOKIE, tokens.refresh_token, REFRESH_DAYS * 24 * 3600),
  ];
}

/** Cookies that delete the session. */
export function clearedCookies(): CookieSpec[] {
  return [base(ACCESS_COOKIE, "", 0), base(REFRESH_COOKIE, "", 0)];
}
