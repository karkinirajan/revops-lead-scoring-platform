export type Bucket = { range: string; count: number };

/** A bar's height as a percentage of the tallest bucket. Empty buckets keep a 2% sliver so the axis stays readable. */
export function barHeightPct(count: number, tallest: number): number {
  return Math.max(2, (count / Math.max(tallest, 1)) * 100);
}

/** The score a bucket starts at, from its "70-79" label; 0 when the label is not in that form. */
export function bucketStart(range: string): number {
  const start = Number.parseInt(range.split("-")[0], 10);
  return Number.isFinite(start) ? start : 0;
}

/** Bars are coloured by the score band the bucket starts in: hot from 75, warm from 50, cool from 25, cold below. */
export function bucketColor(start: number): string {
  if (start >= 75) return "var(--hot)";
  if (start >= 50) return "var(--yellow)";
  if (start >= 25) return "var(--primary)";
  return "var(--text-faint)";
}

export function tallestBucket(buckets: Bucket[] | undefined): number {
  return buckets?.reduce((tallest, bucket) => Math.max(tallest, bucket.count), 1) ?? 1;
}
