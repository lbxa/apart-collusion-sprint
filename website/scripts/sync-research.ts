import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import sources from "../data-sources.json";
import { projectResearch } from "../src/lib/research-export";

const website = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repository = resolve(website, "..");
const check = process.argv.includes("--check");
const sha256 = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

function readPinned(source: { path: string; sha256: string }) {
  const bytes = readFileSync(resolve(repository, source.path));
  if (sha256(bytes) !== source.sha256) throw new Error(`Source changed; review and update data-sources.json: ${source.path}`);
  return bytes;
}

const projection = projectResearch(JSON.parse(readPinned(sources.current).toString()), JSON.parse(readPinned(sources.historical).toString()));
const data = {
  ...projection,
  asOf: sources.asOf,
  provenance: { current: sources.current, historical: sources.historical },
};
const serialized = JSON.stringify(data, null, 2) + "\n";
for (const file of ["src/data/research.json", "public/data/research.json"]) {
  const destination = resolve(website, file);
  if (check) {
    if (!existsSync(destination) || readFileSync(destination, "utf8") !== serialized) throw new Error(`Stale public export: ${file}`);
  } else {
    mkdirSync(dirname(destination), { recursive: true });
    writeFileSync(destination, serialized);
  }
}
for (const paper of sources.papers) {
  const destination = resolve(website, "public/files", paper.file);
  if (existsSync(destination) && sha256(readFileSync(destination)) === paper.sha256) continue;
  if (check) throw new Error(`Missing or changed paper snapshot: ${paper.file}`);
  const bytes = readPinned(paper);
  mkdirSync(dirname(destination), { recursive: true });
  writeFileSync(destination, bytes);
}
console.log(check ? "Public data and paper snapshots match their pinned sources." : "Prepared safe aggregates and separate paper snapshots.");
