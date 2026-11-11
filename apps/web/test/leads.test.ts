import { describe, expect, it } from "vitest";
import { leadsQuery, NO_FILTERS, parseLeadFilters } from "@/lib/leads";

describe("parseLeadFilters", () => {
  it("has no filters when there is nothing in the URL", () => expect(parseLeadFilters({})).toEqual(NO_FILTERS));

  it("reads the tier, in any case", () => {
    expect(parseLeadFilters({ tier: "HOT" }).tier).toBe("HOT");
    expect(parseLeadFilters({ tier: "warm" }).tier).toBe("WARM");
  });

  it.each([["LUKEWARM"], [""], ["HOT,WARM"], ["<script>"]])("drops the tier %j", (tier) => expect(parseLeadFilters({ tier }).tier).toBe(""));

  it("uses the first of a repeated parameter", () => {
    expect(parseLeadFilters({ tier: ["COOL", "HOT"] }).tier).toBe("COOL");
    expect(parseLeadFilters({ min_score: ["40", "90"] }).minScore).toBe("40");
  });

  it.each([["0", "0"], ["50", "50"], ["100", "100"], ["72.5", "72.5"], [" 30 ", "30"]])("keeps min_score %j", (input, kept) => expect(parseLeadFilters({ min_score: input }).minScore).toBe(kept));
  it.each([[""], ["  "], ["-1"], ["101"], ["abc"], ["NaN"], ["Infinity"], ["1e9"]])("drops min_score %j", (input) => expect(parseLeadFilters({ min_score: input }).minScore).toBe(""));

  it.each([["1", 1], ["7", 7], ["120", 120]])("keeps page %j", (input, page) => expect(parseLeadFilters({ page: input }).page).toBe(page));
  it.each([["0"], ["-3"], ["2.5"], ["abc"], [""]])("falls back to page 1 for %j", (input) => expect(parseLeadFilters({ page: input }).page).toBe(1));
});

describe("leadsQuery", () => {
  it("is just paging without filters", () => expect(leadsQuery(NO_FILTERS).toString()).toBe("page=1&page_size=50"));
  it("adds the filters that are set, under the API's names", () => {
    expect(leadsQuery({ tier: "HOT", minScore: "40", page: 3 }, 20).toString()).toBe("page=3&page_size=20&priority_tier=HOT&min_score=40");
  });
  it("keeps a minimum score of 0 out of the query (it is no filter)", () => {
    expect(leadsQuery({ tier: "", minScore: "", page: 1 }).has("min_score")).toBe(false);
  });
});
