const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** Escape text for use in HTML content or a quoted attribute. */
export function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (char) => ESCAPES[char]);
}
