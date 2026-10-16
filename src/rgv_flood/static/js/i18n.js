/* Interface text from the catalog the page embeds (rgv_flood/i18n/en.json). */

const catalog = JSON.parse(document.getElementById("i18n")?.textContent || "{}");

/** The message for `key`, with `{name}` placeholders filled from `params`. */
export function t(key, params = {}) {
  const message = catalog[key];
  if (message === undefined) {
    console.error("missing message", key);
    return key;
  }
  return message.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? ""));
}
