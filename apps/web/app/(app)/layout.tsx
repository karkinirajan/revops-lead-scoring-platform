import { AppShell } from "@/components/layout/AppShell";
import { apiFetch } from "@/lib/server/api";

type Me = { email: string; role: string };

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const me = await apiFetch<Me>("/auth/me");
  return <AppShell user={{ email: me.email, role: me.role }}>{children}</AppShell>;
}
