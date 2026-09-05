// #196 review follow-up: shared client-side "Load more" pagination wiring.
// account.astro and admin/moderation.astro each implemented near-identical
// fetch/offset/button-label state machines independently when #196 added
// pagination envelopes to GET /contributions/mine, GET /contributions/mine/votes,
// and GET /contributions — this module is the one shared copy of that state
// machine. It deliberately does NOT know how to build or append a DOM node:
// each page's rows look different (moderation.astro's cards carry
// approve/reject buttons and bulk-selection checkboxes; account.astro's
// don't), so rendering + any per-row wiring stays the caller's job via
// `onRow`. Fetches always use a relative URL built by the caller — never a
// ${baseUrl}-prefixed one (see #218/#228's baked-internal-hostname bug).

export interface LoadMoreOptions<T> {
  button: HTMLButtonElement;
  buildUrl: (offset: number) => string;
  onRow: (row: T) => void;
  onBatchComplete?: (rows: T[], total: number) => void;
  onError?: (message: string) => void;
}

interface PagedEnvelope<T> {
  items: T[];
  total: number;
}

export function wireLoadMore<T>(options: LoadMoreOptions<T>): void {
  const { button, buildUrl, onRow, onBatchComplete, onError } = options;

  button.addEventListener("click", async () => {
    const offset = Number(button.dataset.offset ?? "0");
    button.disabled = true;
    const originalLabel = button.textContent;
    button.textContent = "Loading…";

    try {
      const response = await fetch(buildUrl(offset), { credentials: "include" });
      if (!response.ok) {
        onError?.(`Could not load more (${response.status}).`);
        button.disabled = false;
        button.textContent = originalLabel;
        return;
      }

      const body = (await response.json()) as PagedEnvelope<T>;

      for (const row of body.items) {
        onRow(row);
      }
      onBatchComplete?.(body.items, body.total);

      const newOffset = offset + body.items.length;
      button.dataset.offset = String(newOffset);
      button.dataset.total = String(body.total);

      if (newOffset >= body.total || body.items.length === 0) {
        button.remove();
      } else {
        button.disabled = false;
        button.textContent = `Load more (${newOffset} of ${body.total})`;
      }
    } catch {
      onError?.("Network error — could not load more. Try again.");
      button.disabled = false;
      button.textContent = originalLabel;
    }
  });
}
