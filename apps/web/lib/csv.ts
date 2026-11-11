const FORMULA_START = /^[=+\-@\t\r]/;

/** One CSV field. Quoted when it needs to be (RFC 4180), and defanged when a spreadsheet would read it as a formula (lead names and emails come from CRMs). */
export function csvField(value: unknown): string {
  let text = value === null || value === undefined ? "" : String(value);
  if (FORMULA_START.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(rows: unknown[][]): string {
  return rows.map((row) => row.map(csvField).join(",")).join("\r\n");
}
