import { describe, expect, it } from "vitest";
import { applyStreamLine } from "@/lib/sse";

describe("applyStreamLine", () => {
  it("reads a chunk, keeping its newlines", () => {
    expect(applyStreamLine('data: {"chunk": "line one\\nline two"}')).toEqual({ kind: "chunk", text: "line one\nline two" });
  });
  it("reads the end marker", () => expect(applyStreamLine("data: [DONE]")).toEqual({ kind: "done" }));
  it("reads an error", () => expect(applyStreamLine('data: {"error": "The AI service could not complete this request."}')).toEqual({ kind: "error", message: "The AI service could not complete this request." }));
  it("prefers an error to a chunk in the same event", () => expect(applyStreamLine('data: {"error": "e", "chunk": "c"}')).toEqual({ kind: "error", message: "e" }));
  it.each(["", "event: ping", ": comment", "data:", "data: ", "data: {", "data: not json", "data: 5", "data: null", 'data: {"chunk": ""}', 'data: {"chunk": 5}', 'data: {"error": ""}', 'data: {"error": 5}', 'data: {"error": {"message": "x"}}', 'data: {"error": true}', 'data: {"other": 1}', 'DATA: {"chunk":"x"}'])(
    "skips %j",
    (line) => expect(applyStreamLine(line)).toEqual({ kind: "skip" }),
  );
});
