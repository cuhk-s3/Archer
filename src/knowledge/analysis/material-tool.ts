import { Type } from "@sinclair/typebox";
import { defineTool } from "@earendil-works/pi-coding-agent";
export function historicalMaterialTool(material: string) {
  const lines = material.split("\n");
  return defineTool({
    name: "read_historical_material",
    label: "Read full historical patch and source evidence",
    description:
      "Read any omitted historical material by 1-based line, or search for literal text. Full source is preserved even when the initial prompt is an excerpt. Missing initial context is not an exclusion reason.",
    parameters: Type.Object({
      startLine: Type.Optional(Type.Integer({ minimum: 1 })),
      query: Type.Optional(Type.String()),
    }),
    execute: async (_id, p) => {
      const selected = p.query
        ? lines
            .flatMap((line, i) => (line.includes(p.query!) ? [i] : []))
            .slice(0, 12)
            .map((i) => ({
              start: Math.max(0, i - 4),
              end: Math.min(lines.length, i + 16),
            }))
        : [
            {
              start: (p.startLine ?? 1) - 1,
              end: Math.min(lines.length, (p.startLine ?? 1) + 199),
            },
          ];
      return {
        content: [
          {
            type: "text" as const,
            text:
              `Full material: ${lines.length} lines\n` +
              selected
                .map((r) =>
                  lines
                    .slice(r.start, r.end)
                    .map((l, i) => `${r.start + i + 1}: ${l}`)
                    .join("\n"),
                )
                .join("\n...\n"),
          },
        ],
        details: {},
      };
    },
  });
}
