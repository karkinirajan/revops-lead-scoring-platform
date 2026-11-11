import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError, errorMessage } from "@/lib/errors";
import { ACCESS_COOKIE, apiBase } from "@/lib/config";

/**
 * Call the API from a server component as the signed-in user. Responses are never cached (they are per user); an expired session sends the user to /login
 * (proxy.ts has already refreshed the token if it could), and any other failure throws an ApiError for the page's error boundary.
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) redirect("/login");

  let response: Response;
  try {
    response = await fetch(`${apiBase()}/api/v1${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(init.headers as Record<string, string> | undefined), Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(502, "The API is unreachable.");
  }

  if (response.status === 401) redirect("/login");
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, errorMessage(body, `The API answered ${response.status}.`));
  }
  return (await response.json()) as T;
}
