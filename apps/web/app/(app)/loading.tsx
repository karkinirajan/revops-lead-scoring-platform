export default function Loading() {
  return (
    <div className="p-4 sm:p-8 max-w-7xl mx-auto" role="status" aria-label="Loading">
      <div className="h-7 w-48 rounded-sm animate-pulse mb-3" style={{ background: "var(--surface-overlay)" }} />
      <div className="h-4 w-72 rounded-sm animate-pulse mb-8" style={{ background: "var(--surface-raised)" }} />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-24 rounded-xl animate-pulse" style={{ background: "var(--surface-raised)" }} />
        ))}
      </div>
    </div>
  );
}
