/** An error response from the API (or from the web app's proxy to it). `message` is safe to show to the user. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The text of a FastAPI error body: `detail` is a string, or a list of validation problems with a `msg` each. */
export function errorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((problem) => (problem && typeof problem === "object" ? (problem as { msg?: unknown }).msg : undefined))
      .filter((msg): msg is string => typeof msg === "string");
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}
