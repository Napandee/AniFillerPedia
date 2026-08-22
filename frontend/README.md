# frontend/

Astro app (SSR/on-demand, `@astrojs/node` standalone adapter — see
`astro.config.mjs`), the Playful Fandom design system (`src/styles/tokens.css`,
`src/components/`), and the typed API client codegen pipeline (#11). Scaffolded
in #31; every other Phase 5 page/flow issue builds on top of this shell.

## Running locally

```sh
npm install
cp .env.example .env   # points PUBLIC_API_BASE_URL at your local backend
npm run dev
```

## Design system

Tokens in `src/styles/tokens.css` are lifted directly from the locked
Playful Fandom design canvas (see CLAUDE.local.md "Visual direction") — don't
hand-tune colors/radii here without checking that reference first. Base
components (`Header`, `Footer`, `SearchInput`, `SeriesCard`, `StatusBadge`,
`Button`) live in `src/components/`; the page shell is `src/layouts/Layout.astro`.

## Typed API client

`src/api/schema.d.ts` is generated from the FastAPI backend's own OpenAPI
schema via `openapi-typescript`. `src/api/client.ts` is a thin
`openapi-fetch` wrapper around it — every request/response shape is
compile-time-checked against the real API, no hand-maintained types to drift.

### Regenerating

The backend's API surface changes as more endpoints ship (#12, #13, #14,
etc.) — re-run this whenever it does, and commit the updated `schema.d.ts`:

```sh
npm install          # first time only
npm run generate:api-client
```

By default this points at a local backend (`http://localhost:8000/openapi.json`
— start it per `backend/`'s own conventions first). To regenerate against a
different instance instead:

```sh
API_SCHEMA_URL=https://anifillerpedia.wiki/openapi.json npm run generate:api-client
```

### Using the client

```ts
import { api } from "./src/api/client.js";

const { data, error } = await api.GET("/api/v1/series", {
  params: { query: { q: "naruto", limit: 5 } },
});
```

`data`/`error` and every field on them are fully typed from the real schema
— renaming or removing a backend field breaks the build here, not silently
at runtime.
