/* The only module that talks to the server. Every call goes to /api/v1. */

const inFlight = new Map(); // path -> AbortController of the latest call

/** GET /api/v1/<path> as JSON. A newer call to the same path cancels the older
 * one (its promise rejects with an AbortError, which callers can ignore). */
export async function getJson(path, params = {}) {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== ""));
  const key = path;
  inFlight.get(key)?.abort();
  const controller = new AbortController();
  inFlight.set(key, controller);
  const url = `/api/v1/${path}${query.size ? `?${query}` : ""}`;
  const response = await fetch(url, { signal: controller.signal, headers: { Accept: "application/json" } });
  if (inFlight.get(key) === controller) inFlight.delete(key);
  if (!response.ok) throw Object.assign(new Error(`${url}: ${response.status}`), { status: response.status });
  return response.json();
}

export const isAbort = (error) => error?.name === "AbortError";
