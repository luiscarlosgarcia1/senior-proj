/** The flood-photo layer's stable MapLibre identifiers. */
export const FLOOD_PHOTO_LAYER = "hcdd1-flood-photos";
// Keep both photo category cluster trees equally local at broad zoom.
export const FLOOD_PHOTO_CLUSTER_RADIUS = 24;
export const FLOOD_PHOTO_SOURCE = "src-" + FLOOD_PHOTO_LAYER;
export const FLOOD_PHOTO_OPENABLE_SOURCE = FLOOD_PHOTO_SOURCE + "-openable";
export const FLOOD_PHOTO_LOCATION_SOURCE = FLOOD_PHOTO_SOURCE + "-locations";
export const FLOOD_PHOTO_CLUSTER_LAYER = "lyr-" + FLOOD_PHOTO_LAYER + "-cluster";
export const FLOOD_PHOTO_POINT_LAYER = "lyr-" + FLOOD_PHOTO_LAYER + "-point";
export const FLOOD_PHOTO_OPENABLE_CLUSTER_LAYER = FLOOD_PHOTO_CLUSTER_LAYER + "-openable";
export const FLOOD_PHOTO_LOCATION_CLUSTER_LAYER = FLOOD_PHOTO_CLUSTER_LAYER + "-locations";
export const FLOOD_PHOTO_OPENABLE_POINT_LAYER = FLOOD_PHOTO_POINT_LAYER + "-openable";
export const FLOOD_PHOTO_LOCATION_POINT_LAYER = FLOOD_PHOTO_POINT_LAYER + "-locations";
