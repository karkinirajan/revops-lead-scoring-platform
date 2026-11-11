export type StreamEvent =
  | { kind: "chunk"; text: string }
  | { kind: "error"; message: string }
  | { kind: "done" }
  | { kind: "skip" };

/** One line of the intelligence stream (`data: {"chunk": "..."}`, `data: {"error": "..."}` or `data: [DONE]`) as an event. Anything else is skipped. */
export function applyStreamLine(line: string): StreamEvent {
  if (!line.startsWith("data: ")) return { kind: "skip" };
  const payload = line.slice(6).trim();
  if (payload === "[DONE]") return { kind: "done" };
  try {
    const parsed: unknown = JSON.parse(payload);
    if (parsed && typeof parsed === "object") {
      const { error, chunk } = parsed as { error?: unknown; chunk?: unknown };
      if (typeof error === "string" && error) return { kind: "error", message: error };
      if (typeof chunk === "string" && chunk) return { kind: "chunk", text: chunk };
    }
  } catch {
    // a partial or malformed line
  }
  return { kind: "skip" };
}
