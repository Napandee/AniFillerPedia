import type { APIRoute } from "astro";

// Proxies to the backend rather than just discarding the cookie client-side:
// afp_session is httpOnly (can't be cleared by client JS), and a real
// server-side logout is what actually invalidates it, not just a client
// belief that it did.
export const POST: APIRoute = async ({ request, redirect }) => {
  const cookie = request.headers.get("cookie");
  const baseUrl = import.meta.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  const backendResponse = await fetch(`${baseUrl}/api/v1/auth/logout`, {
    method: "POST",
    headers: cookie ? { cookie } : undefined,
  });

  const response = redirect("/", 303);
  const setCookie = backendResponse.headers.get("set-cookie");
  if (setCookie) {
    response.headers.append("set-cookie", setCookie);
  }
  return response;
};
