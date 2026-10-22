/** A patch to a MIR .diff file has TWO independent +/- layers. Keep them explicit. */
export const ANALYSIS_VERSION = "nested-mir-diff-v2";
export interface MirDiffViews {
  path: string;
  oldBefore: string;
  oldAfter: string;
  newBefore: string;
  newAfter: string;
}
export function mirDiffViews(patch: string): MirDiffViews[] {
  const result: MirDiffViews[] = [];
  for (const block of patch.split(/(?=^diff --git )/m)) {
    const header = block.match(/^diff --git a\/(.*?) b\/(.*?)$/m);
    if (
      !header ||
      !header[1]!.endsWith(".diff") ||
      !header[2]!.endsWith(".diff")
    )
      continue;
    const old: string[] = [],
      next: string[] = [];
    let inHunk = false;
    for (const line of block.split("\n")) {
      if (line.startsWith("@@")) {
        inHunk = true;
        continue;
      }
      if (!inHunk || line.startsWith("\\")) continue;
      if (line.startsWith(" ")) {
        old.push(line.slice(1));
        next.push(line.slice(1));
      } else if (line.startsWith("-")) old.push(line.slice(1));
      else if (line.startsWith("+")) next.push(line.slice(1));
    }
    if (![...old, ...next].some((l) => /MIR for .* (?:before|after) /.test(l)))
      continue;
    const split = (lines: string[]) => ({
      before: lines
        .filter((l) => !l.startsWith("+"))
        .map((l) => (l.startsWith("-") ? l.slice(1) : l))
        .join("\n"),
      after: lines
        .filter((l) => !l.startsWith("-"))
        .map((l) => (l.startsWith("+") ? l.slice(1) : l))
        .join("\n"),
    });
    const a = split(old),
      b = split(next);
    result.push({
      path: `${header[1]} -> ${header[2]}`,
      oldBefore: a.before,
      oldAfter: a.after,
      newBefore: b.before,
      newAfter: b.after,
    });
  }
  return result;
}
export function historicalMaterial(raw: {
  pr: { title: string; body: string; patch: string };
  issues: unknown[];
}): string {
  const views = mirDiffViews(raw.pr.patch).sort(
    (a, b) =>
      Number(/miscompil|issue|bug/.test(b.path)) -
      Number(/miscompil|issue|bug/.test(a.path)),
  );
  const normalized = views
    .slice(0, 8)
    .map(
      (v) =>
        `FILE ${v.path}\nOLD REVISION before old pass (fragment):\n${v.oldBefore}\nOLD REVISION after old pass (fragment):\n${v.oldAfter}\nNEW REVISION before replacement pass (fragment):\n${v.newBefore}\nNEW REVISION after replacement pass (fragment):\n${v.newAfter}`,
    )
    .join("\n\n")
    .slice(0, 40000);
  return `${raw.pr.title}\n${raw.pr.body}\n${raw.pr.patch}\n${JSON.stringify(raw.issues)}\n\nHOST-DECODED MIR DIFF LAYERS (changed hunks only, not complete files):\n${normalized}\nThe outer patch edits a test expectation; inner +/- lines describe compiler input/output. A retained test name or old comment does not establish that a replacement pass is incorrect. Compare the actual value assignments in each decoded revision. Distinguish original program, historically wrong transformation, and corrected output. Borrowing restrictions and post-copy overwrites are separate conditions; do not conflate them.`;
}

/** Bound the initial prompt, while making every omitted line available through a read tool. */
export function initialHistoricalMaterial(
  material: string,
  limit = 150_000,
): string {
  if (material.length <= limit) return material;
  const blocks = material.split(/(?=^diff --git )/m);
  const intro = blocks.shift() ?? "";
  const ranked = blocks
    .map((text, i) => ({
      text,
      i,
      priority: /^diff --git .*compiler\/rustc_mir_transform\//.test(text)
        ? 2
        : /^diff --git .*tests\/mir-opt\//.test(text)
          ? 1
          : 0,
    }))
    .sort((a, b) => b.priority - a.priority || a.i - b.i);
  let result = intro.slice(0, 20000);
  for (const block of ranked) {
    if (result.length + block.text.length > limit) {
      if (result.length < limit - 1000)
        result += block.text.slice(0, limit - result.length);
      break;
    }
    result += block.text;
  }
  return (
    result +
    `\n[Initial excerpt: ${material.length} total characters. Remaining source is available through read_historical_material. Do not infer absence from omitted hunks.]`
  );
}
