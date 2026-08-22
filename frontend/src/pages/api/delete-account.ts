import type { APIRoute } from "astro";

// #38: proxies to the backend's DELETE /api/v1/users/me rather than doing
// this from client-side JS directly — same reasoning as pages/api/logout.ts:
// afp_session is httpOnly, so only a real server-side round trip can act on
// it, and the backend's own response is what actually clears the cookie
// (Response.delete_cookie in routers/users.py) via the Set-Cookie header we
// forward back below.
export const POST: APIRoute = async ({ request, redirect }) => {
  const cookie = request.headers.get("cookie");
  const baseUrl = import.meta.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  const backendResponse = await fetch(`${baseUrl}/api/v1/users/me`, {
    method: "DELETE",
    headers: cookie ? { cookie } : undefined,
  });

  // A failed deletion (e.g. an already-invalid session) sends the visitor
  // back to the account page rather than pretending success by redirecting
  // to "/" regardless.
  const response = redirect(backendResponse.ok ? "/" : "/account", 303);
  const setCookie = backendResponse.headers.get("set-cookie");
  if (setCookie) {
    response.headers.append("set-cookie", setCookie);
  }
  return response;
};
