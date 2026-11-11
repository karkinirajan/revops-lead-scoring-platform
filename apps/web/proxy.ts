import { NextResponse, type NextRequest } from "next/server";
import { refreshTokens } from "@/lib/auth/refresh";
import { isPublicPath } from "@/lib/auth/paths";
import { expiresWithin } from "@/lib/auth/tokens";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/config";
import { clearSession, clientAddress, setSession } from "@/lib/server/session";

/**
 * Guards the pages. Signed out: to /login (remembering where to come back to). Access token missing or about to expire but a refresh token present: get a new
 * pair now, so the page that is about to render, and every later request, uses it. The API checks every token itself; this only decides who sees a login page.
 */
export async function proxy(request: NextRequest) {
  if (isPublicPath(request.nextUrl.pathname)) return NextResponse.next();

  const access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;

  if (!expiresWithin(access)) return NextResponse.next();

  if (refresh) {
    const renewed = await refreshTokens(refresh, clientAddress(request));
    if (renewed) {
      // the page being rendered right now must see the new access token, so it goes into the request's cookie header as well as to the browser
      const cookies = request.cookies.getAll().filter((c) => c.name !== ACCESS_COOKIE && c.name !== REFRESH_COOKIE);
      cookies.push({ name: ACCESS_COOKIE, value: renewed.access_token }, { name: REFRESH_COOKIE, value: renewed.refresh_token });
      const headers = new Headers(request.headers);
      headers.set("cookie", cookies.map((c) => `${c.name}=${c.value}`).join("; "));
      return setSession(NextResponse.next({ request: { headers } }), renewed);
    }
  }

  const login = new URL("/login", request.url);
  const wanted = request.nextUrl.pathname + request.nextUrl.search;
  if (wanted !== "/") login.searchParams.set("next", wanted);
  return clearSession(NextResponse.redirect(login));
}

export const config = {
  // every request except static files; the sign-in page and the session and proxy routes are let through by isPublicPath
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
