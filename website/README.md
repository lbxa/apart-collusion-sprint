# Collusion Resistance research companion

This top-level `website/` folder is a self-contained Bun/Astro project following
the approved Epistemics companion's light palette, ruled header, compact shadcn
controls and centred resource links. Its data and author roster belong to the
Collusion Sprint. There is no demo, accordion, backend or paid model call.

```sh
bun install --frozen-lockfile
bun run sync:research
bun run dev -- --port 4330
```

## Evidence and updates

`data-sources.json` pins the final November collection snapshot, the historical
October aggregate, the current working paper and the October paper. The November
readout includes five models, six conditions and a separate recovery cohort. Assigned outcomes
include aborts and unresolved cases. Resistance estimates and confidence
intervals remain unavailable pending independent review. The October
aggregate keeps ambiguous and interrupted cases under its original scope.

`scripts/sync-research.ts` validates report data with Zod and emits identical,
safe JSON projections in `src/data/` and `public/data/`. It copies verified PDFs
from existing report builds. Later builds retain the pinned copies. The current
numerical readout is on the page, in the working paper and in the downloadable JSON.

When new results are admitted, update the report brief and source hashes first,
then synchronise and review the site copy. Do not select the latest directory
automatically, change claims because a file exists, or export raw trajectories.
The existing report exporter owns stratified means and uncertainty; the website
does not recompute scores from pooled counts.

## Boundaries and checks

Astro renders prose, counts and links into static HTML. One React island
hydrates the Base UI condition select. The Astro script switches between
pre-rendered outcome panels while the coverage table remains visible. The
historical figure reveals once on scroll and respects reduced motion. Static
charts remain readable without JavaScript. No fonts, images or videos block the
initial page render. Workers deployment serves the static build directly;
no production domain is configured yet.

```sh
bun run lint
bun run typecheck
bun test
bun run build
```

The repository gate is `bash scripts/verify.sh`; it does not validate this site's
build. Browser review should cover narrow and wide layouts, filter changes,
unavailable values, download links, no-JavaScript and reduced-motion views.
The first draft's checks and remaining gaps are recorded in [REVIEW.md](REVIEW.md).

## Cloudflare Workers

`wrangler.jsonc` names the Worker `collusion` and serves `dist/` through Workers
Static Assets. Wrangler runs `bun run build` before deploying, including the
pinned-data checks. No server entrypoint or Astro server adapter is needed.
The custom `src/pages/404.astro` builds to `dist/404.html`; Workers serves it
with a 404 status for missing paths, including nested URLs.

From this folder:

```sh
bun run deploy:check
bun run deploy
```

The first command validates and builds without uploading. The second publishes
using Wrangler's authenticated account. Keep credentials in Wrangler's local
authentication or CI secrets. No account ID, token or custom domain is stored
in the config. The default endpoint uses `workers.dev`.

For Cloudflare Git integration, set the root directory to `website` and deploy
command to `bun run deploy`. Install dependencies with
`bun install --frozen-lockfile`; Wrangler already invokes the build command.
The Cloudflare Worker/project name must match `collusion` in the config.

## Changelog

- 2026-11-18: Publish the latest working manuscript at the existing paper URL.
  Pin its approved build in `data-sources.json` and keep the October paper
  available for the historical cohort.
- 2026-11-18: The current chart uses assigned-case counts from the frozen
  November report. Keep the recovery cohort separate and preserve aborts and
  unresolved cases so coverage gaps cannot appear as resistance.
- 2026-11-17: Added a static 404 page matching the research site's typography,
  palette and rules, with a home link using the existing shadcn button. It
  needs no client JavaScript and uses Workers' existing 404 routing.
- 2026-11-17: Added a pinned Wrangler CLI and static-assets deployment config.
  Deployments build the site and validate the pinned evidence first; a dry-run
  command checks that path without publishing.
- 2026-11-17: Author metadata confirmed by Lucas: Lucas Barbosa, Sravika Linga,
  Muskaan Kumar and Jake Fogel are affiliated with NYU; Stefan Gazzana (two z's)
  is affiliated with Roundarc. The website uses the corrected spelling even
  while its pinned paper snapshot retains the earlier author metadata.
- 2026-11-17: Created the top-level website using the approved research-page
  recipe. Transfer layout and components while preserving Collusion's authors,
  prospective status, independent evidence sources and historical boundaries.
  See [the decision](../docs/decisions/collusion-website-transfers-design-without-transferring-findings.md).
