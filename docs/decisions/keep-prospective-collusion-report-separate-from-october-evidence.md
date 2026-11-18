# Keep the prospective Collusion report separate from October evidence

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** Research report and evidence admission

## Context

The active Collusion report is being developed alongside a new bounded model
campaign. The October manuscript contains genuine historical case studies under
different prompts, mechanisms, and evidence limitations. Reusing its results as
new observations would obscure the change in research question and protocol.
Lucas requested the Epistemics report's visual layout while preserving all five
existing Collusion coauthors.

## Decision

Use `report/agentic/main.tex` for the prospective resistance benchmark. Preserve
the October manuscript as `historical-october-main.tex` and give it a separate
build target. Reuse only the requested layout conventions: Computer Modern,
the ruled title block, Apart structure, and black-outline output panels.
Retain Lucas Barbosa, Stefan Gazana, Sravika Linga, Muskaan Kumar, and Jake Fogel
in their supplied order. Admit new claims only after the reporting brief maps
them to versioned evidence and the review record names remaining gaps.

## Consequences

The active report remains visibly provisional while new evidence is absent.
Historical excerpts may explain a mechanism when attributed with original
rules and exact locators; they do not fill new campaign denominators, establish
new constitutional violations, or justify a model ranking. The separate
historical build preserves access to the full October argument and inventory.
