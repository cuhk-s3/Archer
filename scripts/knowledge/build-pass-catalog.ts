import { readFile, writeFile } from "node:fs/promises";
import { catalogFromSnapshots } from "../../src/rust/passes.js";
const root = new URL("../../knowledge/rust/catalog/", import.meta.url);
const snapshots = JSON.parse(
  await readFile(new URL("sources/snapshots.json", root), "utf8"),
);
const inputs = [];
for (const snapshot of snapshots) {
  inputs.push({
    source: await readFile(
      new URL(`sources/${snapshot.asOf.slice(0, 10)}-mir.rs`, root),
      "utf8",
    ),
    url: snapshot.mirSource,
  });
}
await writeFile(
  new URL("sources/snapshots.json", root),
  JSON.stringify(snapshots, null, 2) + "\n",
);
const passes = catalogFromSnapshots(inputs);
await writeFile(
  new URL("pass-catalog.json", root),
  JSON.stringify(
    {
      schemaVersion: 1,
      period: { since: "2024-01-01", until: "2025-12-31" },
      sources: snapshots,
      passes,
    },
    null,
    2,
  ) + "\n",
);
console.log(
  `Built ${passes.length} pass definitions from pinned Rust source (no ownership mapping).`,
);
