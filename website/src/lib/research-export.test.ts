import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import sources from "../../data-sources.json";
import { projectResearch } from "./research-export";

const current = JSON.parse(readFileSync(new URL("../../../" + sources.current.path, import.meta.url), "utf8"));
const historical = JSON.parse(readFileSync(new URL("../../../" + sources.historical.path, import.meta.url), "utf8"));

describe("public research boundary", () => {
  test("retains the assigned denominator and outcomes for all five models", () => {
    const data = projectResearch(current, historical);
    expect(data.conditions).toHaveLength(7);
    expect(data.models.map(({ id, outcomes: { primary: row } }) =>
      [id, row.assigned, row.correct, row.adverse, row.aborted, row.unresolved])).toEqual([
      ["deepseek", 20, 4, 0, 10, 6],
      ["glm", 20, 12, 0, 8, 0],
      ["kimi", 20, 17, 0, 3, 0],
      ["gptoss", 20, 14, 2, 4, 0],
      ["inkling", 20, 20, 0, 0, 0],
    ]);
    expect(data.resistanceEstimate).toBeNull();
    expect(data.resistanceCI95).toBeNull();
  });
  test("rejects dropped or duplicate model-condition cells and invalid case totals", () => {
    const changed = structuredClone(current);
    const rows = changed.cohorts.original_confirmation.by_model_arm;
    rows[1] = rows[0];
    expect(() => projectResearch(changed, historical)).toThrow();
    const mismatched = structuredClone(current);
    mismatched.cohorts.original_confirmation.by_model_arm[0].missing_case_evidence += 1;
    expect(() => projectResearch(mismatched, historical)).toThrow();
  });
  test("keeps recovery separate even when an original assignment is unresolved", () => {
    const data = projectResearch(current, historical);
    expect(data.original).toMatchObject({ assigned: 300, correct: 122, adverse: 2, aborted: 26, unresolved: 150 });
    expect(data.recovery).toMatchObject({ assigned: 150, correct: 43, adverse: 0, aborted: 3, unresolved: 104, sessions: 75, completed: 19, failed: 51, interrupted: 5 });
    const changed = structuredClone(current);
    changed.cohorts.exploratory_recovery.assigned_cases = 0;
    expect(() => projectResearch(changed, historical)).toThrow();
  });
  test("retains the separate October denominator and ambiguous cases", () => {
    const data = projectResearch(current, historical);
    expect(data.historical.runs).toBe(13);
    expect(data.historical.assigned).toBe(19);
    expect(data.historical.terminal).toBe(18);
    expect(data.historical.categories.map(category => category.count)).toEqual([7, 3, 8, 1]);
  });
  test("strips operator details and episode-level evidence", () => {
    const changed = structuredClone(current);
    changed.operator_secret = "never-export-this";
    changed.roster[0].operator_secret = "never-export-this";
    changed.cohorts.original_confirmation.by_model_arm[0].run_directory = "never-export-this";
    const data = JSON.stringify(projectResearch(changed, historical));
    for (const field of ["never-export-this", "case_observations", "run_directory", "proof_locators", "payoffs_wei", "model_settings", "lbxa-corp"]) expect(data).not.toContain(field);
  });
  test("rejects unknown historical labels and missing model slots", () => {
    const changed = structuredClone(historical);
    changed.runs[0].episodes[0].review.classification = "safe";
    expect(() => projectResearch(current, changed)).toThrow();
    expect(() => projectResearch({ ...current, roster: current.roster.slice(1) }, historical)).toThrow();
  });
});
