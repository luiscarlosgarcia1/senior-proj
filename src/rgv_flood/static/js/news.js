/* A source-first view of the water-news archive. The selected publisher owns the main reading pane. */

import { getJson, isAbort } from "./api.js";
import { t } from "./i18n.js";
import { day } from "./panels/format.js";

function initials(name) {
  const known = {
    "KRGV Channel 5 News": "C5",
    ValleyCentral: "VC",
  };
  if (known[name]) return known[name];
  return name.split(/\s+/).filter((word) => /[A-Za-z]/.test(word)).slice(0, 2).map((word) => word[0]).join("").toUpperCase();
}

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;
  Alpine.data("newsPage", () => ({
    stories: [], activeOutlet: "", activeTopic: "", loading: true,
    init() { Alpine.effect(() => this.load(Alpine.store("app").county)); },
    async load(county) {
      this.loading = true;
      this.activeTopic = "";
      try {
        this.stories = await getJson("news", { county: county || null });
        if (!this.outlets.some((outlet) => outlet.name === this.activeOutlet)) this.activeOutlet = this.outlets[0]?.name || "";
      } catch (error) {
        if (!isAbort(error)) console.warn("news archive unavailable", error);
        this.stories = [];
        this.activeOutlet = "";
      } finally { this.loading = false; }
    },
    get outlets() {
      const groups = new Map();
      for (const story of this.stories) {
        const outlet = groups.get(story.publisher) || { name: story.publisher, stories: [], topics: new Set() };
        outlet.stories.push(story);
        story.topics.forEach((topic) => outlet.topics.add(topic));
        groups.set(story.publisher, outlet);
      }
      return [...groups.values()].map((outlet) => ({ ...outlet, count: outlet.stories.length, latest: outlet.stories[0], initials: initials(outlet.name) }))
        .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name));
    },
    get active() { return this.outlets.find((outlet) => outlet.name === this.activeOutlet); },
    get activeStories() { return this.active?.stories || []; },
    get filteredStories() { return this.activeTopic ? this.activeStories.filter((story) => story.topics.includes(this.activeTopic)) : this.activeStories; },
    get outletTopics() { return [...(this.active?.topics || [])].sort(); },
    get topicComparison() {
      return this.outletTopics.map((topic) => ({
        topic,
        outlet: this.activeStories.filter((story) => story.topics.includes(topic)).length,
        archive: this.stories.filter((story) => story.topics.includes(topic)).length,
      }));
    },
    get activeInitials() { return this.active?.initials || "—"; },
    get activeSummary() { return this.active ? t("news.atlas.active_summary", { stories: this.active.count.toLocaleString() }) : ""; },
    get storyTotal() { return this.stories.length.toLocaleString(); },
    get leadingOutlet() { return this.outlets[0]?.name || "—"; },
    get archiveLabel() { return this.stories.length ? t("news.atlas.archive_summary", { stories: this.storyTotal }) : ""; },
    get outletCountLabel() { return this.outlets.length ? t("news.atlas.outlet_count", { outlets: this.outlets.length }) : ""; },
    selectOutlet(name) { this.activeOutlet = name; this.activeTopic = ""; },
    toggleTopic(topic) { this.activeTopic = this.activeTopic === topic ? "" : topic; },
    outletClass(name) { return name === this.activeOutlet ? "border-brand ring-1 ring-brand/25" : "border-line"; },
    topicClass(topic) { return topic === this.activeTopic ? "border-brand bg-brand text-white" : "border-line bg-bg text-muted hover:border-brand/60"; },
    outletSummary(outlet) { return t("news.atlas.outlet_summary", { stories: outlet.count.toLocaleString(), date: day(outlet.latest.published_at) }); },
    storyDate(story) { return day(story.published_at); },
    topicLabel(topic) { return t(`news.atlas.topic.${topic}`); },
  }));
});
