/* The chat box: ask questions about the project's data in plain language.
 *
 * Answers are put on the page as text only (never as HTML). The conversation
 * lives in this component and is gone when the page reloads; the last ten
 * turns are sent with each question so the assistant can follow along.
 * Data: POST /api/v1/chat, GET /api/v1/chat/status. */

import { getJson, isAbort } from "./api.js";
import { t } from "./i18n.js";

const HISTORY_TURNS = 10;

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  Alpine.data("chatBox", () => ({
    open: false,
    messages: [],
    draft: "",
    busy: false,
    status: null,
    error: "",
    offerSignin: false,
    lastId: 0,

    toggle() {
      this.open = !this.open;
      if (this.open && !this.status) this.loadStatus();
      if (this.open) this.$nextTick(() => this.$root.querySelector("[data-chat-input]")?.focus());
    },
    async loadStatus() {
      try {
        this.status = await getJson("chat/status");
      } catch (error) {
        if (!isAbort(error)) console.warn("chat status unavailable", error);
      }
    },
    onKey(event) {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        this.send();
      }
    },

    async send() {
      const text = this.draft.trim();
      if (!text || this.busy) return;
      const history = this.messages.slice(-HISTORY_TURNS).map((m) => ({ role: m.role, content: m.text }));
      this.busy = true;
      this.error = "";
      this.offerSignin = false;
      this.draft = "";
      const asked = { id: ++this.lastId, role: "user", text };
      this.messages.push(asked);
      try {
        const response = await fetch("/api/v1/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ message: text, history }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw Object.assign(new Error("chat failed"), { body });
        this.messages.push({ id: ++this.lastId, role: "assistant", text: body.answer });
        if (this.status) this.status = { ...this.status, remaining: body.remaining, limit: body.limit, signed_in: body.signed_in };
      } catch (error) {
        // Nothing was answered: take the question back out and give it back to the reader to resend.
        this.messages = this.messages.filter((m) => m.id !== asked.id);
        this.draft = text;
        this.error = typeof error.body?.detail === "string" ? error.body.detail : t("chat.error");
        this.offerSignin = Boolean(error.body?.signin);
        if (error.body?.signin) this.loadStatus();
      } finally {
        this.busy = false;
        this.$nextTick(() => {
          const log = this.$root.querySelector("[data-chat-log]");
          if (log) log.scrollTop = log.scrollHeight;
        });
      }
    },

    // ---- text and state for the template
    get cannotSend() {
      return this.busy || this.draft.trim() === "";
    },
    get signedIn() {
      return Boolean(this.status?.signed_in);
    },
    get canSignIn() {
      return Boolean(this.status?.login_enabled) && !this.signedIn;
    },
    get showSignin() {
      return this.canSignIn || this.offerSignin;
    },
    get account() {
      return this.status?.email ? t("chat.account", { email: this.status.email }) : "";
    },
    get leftText() {
      if (!this.status) return "";
      if (this.status.signed_in) return t("chat.unlimited");
      const n = this.status.remaining ?? 0;
      return t(n === 1 ? "chat.left_one" : "chat.left", { n });
    },
    get signinUrl() {
      return `/auth/login?next=${encodeURIComponent(location.pathname)}`;
    },
    get empty() {
      return this.messages.length === 0 && !this.error;
    },
    // inside x-for: `this.message`
    bubbleClass() {
      return this.message.role === "user"
        ? "ml-auto bg-accent-soft"
        : "mr-auto bg-panel2";
    },
  }));
});
