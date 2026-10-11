/** GET a JSON resource. Resolves to null when the server has nothing to give
 * (for example a layer the pipeline hasn't built yet). */
export async function fetchJson(url, options) {
  const response = await fetch(url, options);
  return response.ok ? response.json() : null;
}
