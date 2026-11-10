/* The methods components/news_story.html calls, for any component that lists stories as `story` in an x-for
 * (the map's news panel, an event's news, the news page's timeline). */

import { day } from "./panels/format.js";

export const storyMethods = {
  storyMeta() {
    return [this.story.publisher, day(this.story.published_at), this.story.city].filter(Boolean).join(" · ");
  },
  fromAddress() {
    return this.story.headline_from === "address";
  },
  hasOthers() {
    return (this.story.also_reported_by || []).length > 0;
  },
};
