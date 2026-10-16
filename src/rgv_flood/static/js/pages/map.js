/* The map page's one entry module. Everything else is imported from here, so each
 * module runs exactly once (a module loaded both by a versioned <script> tag and
 * by an import would run twice). */

import "../panels/layer-panel.js";
import "../map/popups.js";
import "../panels/alerts.js";
import "../panels/events.js";
import "../panels/records.js";
