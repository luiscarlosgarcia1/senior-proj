"""The chat box. Every request is answered by the test itself (page.route); the real chat endpoint and the model are never reached."""

import json
import re

from playwright.sync_api import expect

STATUS = {"enabled": True, "login_enabled": True, "signed_in": False, "email": None, "remaining": 5, "limit": 5}
CHAT = re.compile(r".*/api/v1/chat$")
CHAT_STATUS = re.compile(r".*/api/v1/chat/status$")


class Stub:
    """Answers the page's chat requests from a script and remembers what was sent."""

    def __init__(self, page, answers=None, status=None, hold=False):
        self.answers = list(answers or [])
        self.sent = []
        self.held = []
        self.hold = hold
        self.status = {**STATUS, **(status or {})}
        page.route(CHAT_STATUS, lambda route: route.fulfill(json=self.status))
        page.route(CHAT, self.answer)

    def answer(self, route):
        self.sent.append(json.loads(route.request.post_data))
        if self.hold:
            self.held.append(route)
            return
        self.respond(route)

    def respond(self, route):
        reply = self.answers.pop(0) if self.answers else {"status": 200, "json": {"answer": "ok", "remaining": 3, "limit": 5, "signed_in": False}}
        route.fulfill(status=reply["status"], json=reply["json"])


def ok(text, remaining=4):
    return {"status": 200, "json": {"answer": text, "remaining": remaining, "limit": 5, "signed_in": False}}


def open_chat(page, server, stub_args=None, path="/claims"):
    stub = Stub(page, **(stub_args or {}))
    page.goto(f"{server}{path}")
    page.locator("[data-chat-toggle]").click()
    expect(page.locator("[data-chat-panel]")).to_be_visible()
    return stub


def ask(page, text):
    page.locator("[data-chat-input]").fill(text)
    page.locator("[data-chat-send]").click()


def test_toggle_opens_and_closes_the_panel(page, chat_server):
    Stub(page)
    page.goto(f"{chat_server}/claims")
    toggle, panel = page.locator("[data-chat-toggle]"), page.locator("[data-chat-panel]")

    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(panel).to_be_hidden()
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(panel).to_be_visible()
    page.locator("[data-chat-close]").click()
    expect(panel).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")


def test_the_box_is_on_the_home_page_and_the_map_page_too(page, chat_server):
    Stub(page)
    for path in ("/", "/map", "/trends"):
        page.goto(f"{chat_server}{path}")
        expect(page.locator("[data-chat-toggle]")).to_be_visible()


def test_sending_shows_the_question_then_the_answer(page, chat_server):
    stub = open_chat(page, chat_server, {"answers": [ok("2020 had the most claims.")]})

    ask(page, "Which year had the most claims?")

    messages = page.locator("[data-chat-message]")
    expect(messages).to_have_text(["Which year had the most claims?", "2020 had the most claims."])
    assert stub.sent == [{"message": "Which year had the most claims?", "history": []}]
    expect(page.locator("[data-chat-input]")).to_have_value("")


def test_answer_markup_is_shown_as_text(page, chat_server):
    open_chat(page, chat_server, {"answers": [ok("<b>bold</b><img src=x onerror=alert(1)>")]})

    ask(page, "hello")

    log = page.locator("[data-chat-log]")
    expect(log).to_contain_text("<b>bold</b><img src=x onerror=alert(1)>")
    expect(log.locator("b, img")).to_have_count(0)


def test_messages_left_follow_each_answer(page, chat_server):
    open_chat(page, chat_server, {"answers": [ok("a", 4), ok("b", 3)]})
    left = page.locator("[data-chat-left]")

    expect(left).to_have_text("5 messages left today")
    ask(page, "one")
    expect(left).to_have_text("4 messages left today")
    ask(page, "two")
    expect(left).to_have_text("3 messages left today")


def test_the_limit_message_offers_sign_in(page, chat_server):
    open_chat(page, chat_server, {"answers": [{"status": 429, "json": {"detail": "You have used today's 5 messages.", "signin": True}}]},
              path="/claims")

    ask(page, "one more")

    expect(page.locator("[data-chat-error]")).to_contain_text("used today's 5 messages")
    link = page.locator("[data-chat-signin]")
    expect(link).to_be_visible()
    assert link.get_attribute("href") == "/auth/login?next=%2Fclaims"
    expect(page.locator("[data-chat-input]")).to_have_value("one more")  # nothing was lost


def test_enter_sends_and_shift_enter_adds_a_line(page, chat_server):
    stub = open_chat(page, chat_server)
    box = page.locator("[data-chat-input]")

    box.fill("first line")
    box.press("Shift+Enter")
    box.type("second line")
    assert stub.sent == []
    box.press("Enter")

    expect(page.locator("[data-chat-message]").first).to_have_text("first line\nsecond line")
    assert [s["message"] for s in stub.sent] == ["first line\nsecond line"]


def test_a_failed_message_shows_an_error_and_keeps_the_draft(page, chat_server):
    open_chat(page, chat_server, {"answers": [{"status": 502, "json": {"detail": "The assistant is unavailable right now. Try again in a moment."}}]})

    ask(page, "will it work?")

    expect(page.locator("[data-chat-error]")).to_contain_text("unavailable right now")
    expect(page.locator("[data-chat-input]")).to_have_value("will it work?")
    expect(page.locator("[data-chat-message]")).to_have_count(0)  # the unanswered question is not left hanging


def test_while_waiting_it_cannot_be_sent_twice(page, chat_server):
    stub = open_chat(page, chat_server, {"hold": True})

    ask(page, "slow question")
    send = page.locator("[data-chat-send]")
    expect(send).to_be_disabled()
    page.locator("[data-chat-input]").fill("impatient second question")
    page.locator("[data-chat-input]").press("Enter")
    page.wait_for_timeout(200)

    assert len(stub.sent) == 1
    stub.respond(stub.held[0])
    expect(page.locator("[data-chat-message]")).to_have_count(2)
    expect(send).to_be_enabled()


def test_at_most_ten_earlier_turns_are_sent(page, chat_server):
    stub = open_chat(page, chat_server)

    for number in range(1, 13):
        ask(page, f"question {number}")
        expect(page.locator("[data-chat-message]")).to_have_count(2 * number)

    last = stub.sent[-1]
    assert last["message"] == "question 12" and len(last["history"]) == 10
    assert last["history"][0] == {"role": "user", "content": "question 7"}
    assert [turn["role"] for turn in last["history"]] == ["user", "assistant"] * 5


def test_signed_in_shows_the_email_and_unlimited(page, chat_server):
    open_chat(page, chat_server, {"status": {"signed_in": True, "email": "ana@utrgv.edu", "remaining": 199, "limit": 200}})

    expect(page.locator("[data-chat-left]")).to_have_text("Unlimited messages")
    expect(page.locator("[data-chat-account]")).to_contain_text("ana@utrgv.edu")
    expect(page.locator("[data-chat-signin]")).to_be_hidden()
    expect(page.locator("[data-chat-signout]")).to_have_attribute("href", "/auth/logout")


def test_no_sign_in_link_when_sign_in_is_not_set_up(page, chat_server):
    open_chat(page, chat_server, {"status": {"login_enabled": False}})

    expect(page.locator("[data-chat-signin]")).to_be_hidden()


def test_it_fits_a_phone(page, chat_server):
    page.set_viewport_size({"width": 375, "height": 700})
    open_chat(page, chat_server)

    assert page.evaluate("document.documentElement.scrollWidth") <= 375
    box = page.locator("[data-chat-panel]").bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375


def test_the_notice_says_this_is_not_emergency_guidance(page, chat_server):
    open_chat(page, chat_server)

    expect(page.locator("[data-chat-panel]")).to_contain_text("not emergency guidance")


def test_no_console_errors(page, chat_server, console_errors):
    open_chat(page, chat_server, {"answers": [ok("fine")]})
    ask(page, "hi")
    expect(page.locator("[data-chat-message]")).to_have_count(2)

    assert console_errors == []

