export function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
}) {
  return (
    <div
      className="rounded-xl p-5 flex flex-col gap-2 border"
      style={{ background: "var(--surface-raised)", borderColor: "var(--border)" }}
    >
      <p className="text-xs font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {label}
      </p>
      <p
        className="text-3xl font-bold tabular-nums"
        style={{ color: accent ?? "var(--text)" }}
      >
        {value}
      </p>
      {sub && (
        <p className="text-xs" style={{ color: "var(--text-faint)" }}>
          {sub}
        </p>
      )}
    </div>
  );
}
