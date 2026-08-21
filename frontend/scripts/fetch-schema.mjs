// Fetches the backend's live OpenAPI schema and saves it to
// src/api/openapi.json, which openapi-typescript then reads. Local backend
// is the default target (this is a build-time dev tool, not something that
// should silently depend on the production site being up) — override with
// API_SCHEMA_URL for CI or to regenerate against the live droplet.
//
// Local default assumes the backend is running per its own README/Dockerfile
// conventions (uvicorn on :8000, /openapi.json auto-exposed by FastAPI).

import { writeFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_LOCAL_URL = "http://localhost:8000/openapi.json";
const url = process.env.API_SCHEMA_URL ?? DEFAULT_LOCAL_URL;

const outPath = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "api", "openapi.json");

console.log(`Fetching OpenAPI schema from ${url} ...`);

let res;
try {
  res = await fetch(url);
} catch (err) {
  console.error(`Could not reach ${url}.`);
  console.error(
    "Is the backend running locally? Start it per backend/README conventions " +
      "(uvicorn, :8000), or point at another instance:\n" +
      "  API_SCHEMA_URL=https://anifillerpedia.wiki/openapi.json npm run generate:api-client"
  );
  console.error(String(err));
  process.exit(1);
}

if (!res.ok) {
  console.error(`Fetch failed: ${res.status} ${res.statusText}`);
  process.exit(1);
}

const schema = await res.json();
await mkdir(dirname(outPath), { recursive: true });
await writeFile(outPath, JSON.stringify(schema, null, 2) + "\n");

console.log(`Saved ${Object.keys(schema.paths ?? {}).length} paths to ${outPath}`);
