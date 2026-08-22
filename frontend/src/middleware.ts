import { defineMiddleware } from "astro:middleware";
import { createApiClient } from "./api/client";

// #37: session state is re-derived from the backend on every request (via
// the browser's own afp_session cookie, forwarded here), never held in
// server or client memory across requests — a fresh page load always
// reflects the real session, including immediately after login/logout.
export const onRequest = defineMiddleware(async (context, next) => {
  context.locals.user = null;

  const cookie = context.request.headers.get("cookie");
  if (cookie) {
    const api = createApiClient(import.meta.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000");
    // A logged-out visitor's cookie-less request never reaches this branch
    // at all; an expired/invalid cookie still reaches it but /users/me
    // correctly 401s (data stays undefined) rather than throwing — that 401
    // is the expected "not logged in" case, not an error to surface.
    const { data } = await api.GET("/api/v1/users/me", { headers: { cookie } });
    if (data) {
      context.locals.user = data;
    }
  }

  return next();
});
