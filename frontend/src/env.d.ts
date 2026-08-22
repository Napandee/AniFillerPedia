/// <reference types="astro/client" />

interface ImportMetaEnv {
  /** Base URL of the FastAPI backend, e.g. https://anifillerpedia.wiki */
  readonly PUBLIC_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
