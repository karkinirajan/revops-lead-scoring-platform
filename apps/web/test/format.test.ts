import { describe, expect, it } from "vitest";
import { describeDuration, describeModelScope, sizeTierLabel } from "@/lib/format";

describe("sizeTierLabel", () => {
  it.each([["smb", "SMB"], ["mid_market", "Mid-market"], ["enterprise", "Enterprise"]])("%s → %s", (tier, label) => expect(sizeTierLabel(tier)).toBe(label));
  it("shows an unknown tier readably rather than hiding it", () => {
    expect(sizeTierLabel("strategic_account")).toBe("strategic account");
    expect(sizeTierLabel("very_large_account")).toBe("very large account");
    expect(sizeTierLabel("")).toBe("");
  });
});

describe("describeDuration", () => {
  it.each([[21600, "6 hours"], [3600, "1 hour"], [600, "10 minutes"], [60, "1 minute"], [45, "45 seconds"], [1, "1 second"], [86400, "1 day"], [172800, "2 days"]])("%d s → %s", (seconds, text) => expect(describeDuration(seconds)).toBe(text));
  it("uses the largest unit that divides evenly, so nothing is rounded", () => {
    expect(describeDuration(90)).toBe("90 seconds");
    expect(describeDuration(5400)).toBe("90 minutes");
    expect(describeDuration(90000)).toBe("25 hours");
  });
  it("copes with zero, negatives and fractions", () => {
    expect(describeDuration(0)).toBe("0 seconds");
    expect(describeDuration(-5)).toBe("0 seconds");
    expect(describeDuration(59.6)).toBe("1 minute");
  });
});

describe("describeModelScope", () => {
  it("says so when the report covers every version", () => expect(describeModelScope("all")).toEqual({ value: "All versions", sub: "accuracy across every model version" }));
  it("names a single version", () => expect(describeModelScope("2.0.1")).toEqual({ value: "v2.0.1", sub: "accuracy for this model version only" }));
  it.each([[null], [undefined], [""]])("has a dash when the API reports %j", (version) => expect(describeModelScope(version).value).toBe("—"));
});
