/// <reference types="astro/client" />

interface ImportMetaEnv {
  /** Base URL of the FastAPI backend, e.g. https://anifillerpedia.wiki */
  readonly PUBLIC_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare namespace App {
  interface Locals {
    /** Set by src/middleware.ts on every request; null when logged out. */
    user: import("./api/client").CurrentUser | null;
  }
}
