const SIZE_TIERS: Record<string, string> = { smb: "SMB", mid_market: "Mid-market", enterprise: "Enterprise" };

/** Display label for a company size tier; unknown tiers are shown readably rather than hidden. */
export function sizeTierLabel(tier: string): string {
  return SIZE_TIERS[tier] ?? tier.replace(/_/g, " ");
}

const UNITS: Array<[string, number]> = [["day", 86400], ["hour", 3600], ["minute", 60], ["second", 1]];

/** "6 hours", "1 minute", "90 seconds": the largest unit that divides the duration evenly. */
export function describeDuration(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const [name, size] = UNITS.find(([, size]) => whole >= size && whole % size === 0) ?? UNITS[UNITS.length - 1];
  const count = whole / size;
  return `${count} ${name}${count === 1 ? "" : "s"}`;
}

/** The analytics "model version" card. The API says "all" when the report covers every model version rather than one. */
export function describeModelScope(version: string | null | undefined): { value: string; sub: string } {
  if (!version) return { value: "—", sub: "no model version reported" };
  if (version === "all") return { value: "All versions", sub: "accuracy across every model version" };
  return { value: `v${version}`, sub: "accuracy for this model version only" };
}
