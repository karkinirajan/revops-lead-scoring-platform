import { NextResponse } from "next/server";
import { isSameOrigin } from "@/lib/auth/origin";
import { clearSession } from "@/lib/server/session";

export const dynamic = "force-dynamic";

/** Sign out: delete the session cookies. (Tokens are not revoked at the API, which keeps none; they simply stop being sent, and expire.) */
export async function POST(request: Request) {
  if (!isSameOrigin(request)) return NextResponse.json({ detail: "Cross-site request refused." }, { status: 403 });
  return clearSession(NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } }));
}
