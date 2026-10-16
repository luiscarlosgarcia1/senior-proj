/* Small display helpers shared by the side panels. */

/** "2020-07-25" -> "Jul 25, 2020" (dates are calendar days; never shifted by time zone). */
export function day(iso) {
  if (!iso) return "";
  return new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
  });
}

/** How long ago a UTC timestamp was, in words ("2 min ago", "3 h ago"). */
export function ago(iso) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h ago` : `${Math.round(hours / 24)} days ago`;
}

/** The severity token for a NOAA event type (events carry no severity of their own). */
export function eventSeverity(type) {
  const kind = (type || "").toLowerCase();
  if (kind.includes("flash")) return "high";
  if (kind.includes("coastal")) return "low";
  if (kind.includes("flood")) return "mod";
  return "unc";
}

/** The severity token for an alert's wording. */
export function alertSeverity(summary) {
  const text = (summary || "").toLowerCase();
  if (text.includes("warning") || text.includes("closed") || text.includes("closure")) return "high";
  if (text.includes("watch") || text.includes("advisory")) return "mod";
  return "unc";
}
