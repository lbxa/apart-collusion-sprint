# Website review

## November 18 paper checkpoint

The working-paper download matches the 19-page November manuscript, SHA-256
`af0ceb3e43ef4683fa6ad49c5534260c20725e24aef77d3775b4b9da4c0db482`.
The October download retains its pinned archive. The static output contains
both PDFs at their linked paths. Pinned-data verification, Astro and TypeScript
checks, six data tests and the production build pass.

## November 18 results update

The page and download use the frozen November 17 (Eastern time) counts.
The primary chart shows 20 assigned cases per model. Each of the six
individual conditions shows 10 per model. Recovery remains separate from
original assignments. Both paper downloads retain their earlier hashes.

- Pinned-data verification, source lint, Astro and TypeScript checks, six
  data tests and the production build passed.
- Chromium verified all seven filter views, no page errors, all four
  evidence download links, and the default view with JavaScript disabled.
  Visual checks covered desktop and mobile, including screen widths of
  320 and 390 pixels with no horizontal overflow.
- Local build verified. Public deployment remains pending.

## November 17 site and deployment preparation

Reviewed 2026-11-17 against the pinned sources in `data-sources.json`.

The initial five-model page had no admitted confirmation estimates. Its empty
cells display unavailable values, without zero scores or invented intervals.
The October chart uses the historical episode classifications and retains its
ambiguous and interrupted cases. Those agent-reviewed cases remain separate
from the new cohort and do not estimate a population collusion rate. Working
and historical papers are distinct, verified download snapshots.

## Passed

- Data synchronisation and pinned-source checks.
- ESLint, Astro/TypeScript checks, five data tests with 60 assertions, and the
  production build.
- Production-browser review at 1440 × 844 and 390 × 844: five model rows,
  historical counts of 7 / 3 / 8 / 1, no horizontal overflow, no console errors,
  all three mechanism choices, keyboard dismissal and focus return.
- Both paper downloads, public JSON, study notes and favicon return HTTP 200.
- No-JavaScript view retains readable content and hides the inactive select.
  Reduced motion prevents the historical reveal; changing that preference
  during the reveal cancels it. Scrolling back does not replay the animation.
- `git diff --check` and the generated decision-index check.
- Wrangler 4.164.0 dry-run validates the config, executes the guarded Astro
  build and reads the static assets without uploading. Frozen-lockfile
  installation and type checks also pass.
- Local Workers serving returns the page, JSON, favicon and both PDFs with
  the expected status and content type. Both served PDF hashes match their
  pins; a missing path returns 404.
- The custom 404 page passes visual review at 1280 × 844 and 390 × 844.
  Nested missing URLs return its HTML with a 404 status, no horizontal
  overflow and no client scripts. Its home link works by keyboard, and the
  page renders without JavaScript. Build, lint and type checks pass.
- The repository-wide `bash scripts/verify.sh` rerun after adding the 404 page
  passes, including all 42 engine integration tests. The earlier harness
  formatting blocker is no longer present.

## Remaining

Workers deployment is configured in `wrangler.jsonc`; no public deployment was
performed in this change and no custom domain is configured. See `README.md`
for deployment commands. New evidence needs the admission and synchronisation
steps before changing public claims. The default development command uses port
4330.
