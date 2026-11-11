import { describe, expect, it } from "vitest";
import { csvField, toCsv } from "@/lib/csv";

describe("csvField", () => {
  it.each([["plain", "plain"], ["", ""], [0, "0"], [12.5, "12.5"], [null, ""], [undefined, ""], [true, "true"]])("%j → %j", (value, expected) => {
    expect(csvField(value)).toBe(expected);
  });

  it("quotes a field with a lone carriage return", () => expect(csvField("a\rb")).toBe('"a\rb"'));

  it("quotes a field with a comma, quote or line break, doubling inner quotes", () => {
    expect(csvField("Acme, Inc.")).toBe('"Acme, Inc."');
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
    expect(csvField("two\nlines")).toBe('"two\nlines"');
    expect(csvField("a\r\nb")).toBe('"a\r\nb"');
  });

  it.each(["=SUM(A1:A9)", "+1+1", "-2+3", "@cmd", "\tx", "\rx"])("defangs the formula %j", (value) => {
    expect(csvField(value).replace(/^"|"$/g, "")).toBe(`'${value}`);
  });

  it("defangs and quotes together", () => {
    expect(csvField('=HYPERLINK("http://evil","x")')).toBe(`"'=HYPERLINK(""http://evil"",""x"")"`);
  });

  it("leaves a dash or equals that is not first alone", () => {
    expect(csvField("a-b=c")).toBe("a-b=c");
    expect(csvField("Acme - Corp")).toBe("Acme - Corp");
  });
});

describe("toCsv", () => {
  it("joins fields with commas and rows with CRLF", () => {
    expect(toCsv([["a", "b"], ["1", "2"]])).toBe("a,b\r\n1,2");
  });
  it("is empty for no rows", () => expect(toCsv([])).toBe(""));
  it("round-trips awkward values into the right columns", () => {
    const csv = toCsv([["Name", "Company"], ["Smith, John", 'The "Best" Co']]);
    expect(csv).toBe('Name,Company\r\n"Smith, John","The ""Best"" Co"');
  });
});
