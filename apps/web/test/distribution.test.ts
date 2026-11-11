import { describe, expect, it } from "vitest";
import { barHeightPct, bucketColor, bucketStart, tallestBucket } from "@/lib/distribution";

describe("barHeightPct", () => {
  it("is the bucket's share of the tallest", () => {
    expect(barHeightPct(5, 10)).toBe(50);
    expect(barHeightPct(10, 10)).toBe(100);
    expect(barHeightPct(1, 4)).toBe(25);
  });
  it("keeps a 2% sliver for an empty bucket, and for a tiny one", () => {
    expect(barHeightPct(0, 10)).toBe(2);
    expect(barHeightPct(1, 1000)).toBe(2);
    expect(barHeightPct(2, 100)).toBe(2);
    expect(barHeightPct(3, 100)).toBe(3);
  });
  it("does not divide by zero", () => {
    expect(barHeightPct(0, 0)).toBe(2);
    expect(Number.isFinite(barHeightPct(5, 0))).toBe(true);
  });
});

describe("bucketStart", () => {
  it.each([["0-9", 0], ["70-79", 70], ["90-100", 90], ["25", 25]])("%s → %d", (range, start) => expect(bucketStart(range)).toBe(start));
  it.each([[""], ["abc"], ["-"], ["x-9"]])("is 0 for %j", (range) => expect(bucketStart(range)).toBe(0));
});

describe("bucketColor", () => {
  it.each([
    [0, "var(--text-faint)"], [24, "var(--text-faint)"],
    [25, "var(--primary)"], [49, "var(--primary)"],
    [50, "var(--yellow)"], [74, "var(--yellow)"],
    [75, "var(--hot)"], [90, "var(--hot)"], [100, "var(--hot)"],
  ])("a bucket starting at %d is %s", (start, color) => expect(bucketColor(start)).toBe(color));
});

describe("tallestBucket", () => {
  it("is the largest count", () => expect(tallestBucket([{ range: "0-9", count: 3 }, { range: "10-19", count: 9 }, { range: "20-29", count: 4 }])).toBe(9));
  it("is at least 1, so empty data cannot make a zero denominator", () => {
    expect(tallestBucket([{ range: "0-9", count: 0 }])).toBe(1);
    expect(tallestBucket([])).toBe(1);
    expect(tallestBucket(undefined)).toBe(1);
  });
});
