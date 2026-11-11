import { describe, expect, it } from "vitest";
import { ApiError, errorMessage } from "@/lib/errors";

describe("errorMessage", () => {
  it("uses a string detail", () => expect(errorMessage({ detail: "Not found" }, "x")).toBe("Not found"));
  it("joins FastAPI validation messages", () => {
    expect(errorMessage({ detail: [{ loc: ["body", "email"], msg: "value is not a valid email address", type: "value_error" }, { msg: "Field required" }] }, "x")).toBe(
      "value is not a valid email address; Field required",
    );
  });
  it.each([null, undefined, "text", 5, {}, { detail: "" }, { detail: [] }, { detail: [{}] }, { detail: [null] }, { detail: 5 }, { detail: { msg: "x" } }])("falls back for %j", (body) => {
    expect(errorMessage(body, "fallback")).toBe("fallback");
  });
});

describe("ApiError", () => {
  it("carries the status and message", () => {
    const error = new ApiError(409, "Already registered");
    expect(error).toBeInstanceOf(Error);
    expect([error.name, error.status, error.message]).toEqual(["ApiError", 409, "Already registered"]);
  });
});
