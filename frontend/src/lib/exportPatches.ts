import type { SuggestedPatch } from "@/api/types";

function download(filename: string, text: string, mime: string): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function formatTargetFile(target: string | null | undefined): string {
  const t = (target ?? "").trim();
  if (!t) return "(test defect — no target file; review Healer rationale)";
  return t.startsWith("repo_cache/") ? t : `repo_cache/${t.replace(/^\/+/, "")}`;
}

/** Full patch bundle for download — exact Healer code with file citations. */
export function buildSuggestedPatchesDocument(
  patches: SuggestedPatch[],
  runId: string,
  storyTitle?: string,
): string {
  const lines: string[] = [
    "# Sentinel-QA — suggested patches (Healer)",
    "",
    `- Run: ${runId}`,
    storyTitle ? `- Story: ${storyTitle}` : "",
    `- Count: ${patches.length}`,
    "",
    "Apply manually in your target app under `Backend/repo_cache/` unless paths already include that prefix.",
    "",
    "---",
    "",
  ];

  for (const p of patches) {
    const target = formatTargetFile(p.target_file);
    const tests = (p.related_test_ids?.length ? p.related_test_ids : [p.test_id]).join(", ");
    lines.push(`## ${p.patch_id} — ${p.test_id}`);
    lines.push("");
    lines.push(`**Target file:** \`${target}\``);
    lines.push(`**Related tests:** ${tests}`);
    if (p.owasp_category) lines.push(`**OWASP:** ${p.owasp_category}`);
    if (p.decision && p.decision !== "pending") lines.push(`**Decision:** ${p.decision}`);
    lines.push("");
    if (p.bug_explanation?.trim()) {
      lines.push("### Rationale");
      lines.push("");
      lines.push(p.bug_explanation.trim());
      lines.push("");
    }
    const fix = (p.suggested_fix ?? "").trim();
    if (fix) {
      lines.push("### Suggested code");
      lines.push("");
      lines.push("```python");
      lines.push(fix);
      lines.push("```");
    } else {
      lines.push("_No replacement code — Healer flagged a test/harness defect._");
    }
    lines.push("");
    lines.push("---");
    lines.push("");
  }

  return lines.join("\n");
}

export function downloadSuggestedPatches(
  patches: SuggestedPatch[],
  runId: string,
  storyTitle?: string,
): void {
  const body = buildSuggestedPatchesDocument(patches, runId, storyTitle);
  download(`sentinel_patches_${runId}.md`, body, "text/markdown;charset=utf-8");
}
