/* The landing page's one entry module.
 *
 * Before the landing page existed, the front page was the map, so a shared link
 * is the front page plus a #hash (county, layers, view). Those still open the map. */

if (location.hash.length > 1) location.replace(`/map${location.search}${location.hash}`);
