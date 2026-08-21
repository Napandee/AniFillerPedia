// Thin typed wrapper around the generated OpenAPI schema. Import `api`
// from here anywhere in the frontend once Phase 5 starts — every request/
// response shape is compile-time-checked against schema.d.ts, regenerated
// via `npm run generate:api-client` (see README.md in this directory).
//
// baseUrl is a plain function param rather than reading Astro/Vite's
// import.meta.env directly, so this file type-checks standalone with `tsc`
// before Astro (and its ambient env types) exists — Phase 5 call sites pass
// import.meta.env.PUBLIC_API_BASE_URL in explicitly.
import createClient from "openapi-fetch";
import type { paths } from "./schema.d.ts";

export function createApiClient(baseUrl: string = "https://anifillerpedia.wiki") {
  return createClient<paths>({ baseUrl });
}

export const api = createApiClient();
