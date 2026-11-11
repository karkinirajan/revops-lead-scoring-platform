import type { PriorityTier } from "@/lib/types";

const TIER_STYLES: Record<PriorityTier, { bg: string; text: string; dot: string; label: string }> = {
  HOT: { bg: "rgba(239,68,68,0.12)", text: "#f87171", dot: "#ef4444", label: "HOT" },
  WARM: { bg: "rgba(249,115,22,0.12)", text: "#f97316", dot: "#f97316", label: "WARM" },
  COOL: { bg: "rgba(59,130,246,0.12)", text: "#60a5fa", dot: "#3b82f6", label: "COOL" },
  COLD: { bg: "rgba(107,114,128,0.12)", text: "#9ca3af", dot: "#6b7280", label: "COLD" },
};

export function TierBadge({ tier }: { tier: PriorityTier }) {
  const s = TIER_STYLES[tier] ?? TIER_STYLES.COLD;
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold"
      style={{ background: s.bg, color: s.text }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.dot }} />
      {s.label}
    </span>
  );
}
