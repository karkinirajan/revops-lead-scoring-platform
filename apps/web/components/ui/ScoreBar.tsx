export function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score));
  const color =
    pct >= 75 ? "#ef4444" : pct >= 50 ? "#f97316" : pct >= 25 ? "#3b82f6" : "#6b7280";

  return (
    <div className="flex items-center gap-2 w-full min-w-[80px]">
      <div
        className="flex-1 rounded-full overflow-hidden"
        style={{ height: 4, background: "var(--border)" }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="text-xs font-mono w-6 text-right" style={{ color: "var(--text)" }}>
        {score}
      </span>
    </div>
  );
}
