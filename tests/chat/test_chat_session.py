"""Chat: signed, expiring cookie values (rgv_flood/chat/session.py)."""

import pytest

from rgv_flood.chat.session import sign, unsign

SECRET = "s" * 40


def test_round_trip():
    token = sign({"email": "ana@utrgv.edu"}, SECRET, 3600, now=1000.0)

    assert unsign(token, SECRET, now=1500.0) == {"email": "ana@utrgv.edu"}


def test_the_payload_is_returned_without_its_expiry():
    assert unsign(sign({"a": 1}, SECRET, 60, now=0.0), SECRET, now=1.0) == {"a": 1}


def test_wrong_secret_is_refused():
    token = sign({"email": "ana@utrgv.edu"}, SECRET, 3600, now=1000.0)

    assert unsign(token, "t" * 40, now=1001.0) is None


@pytest.mark.parametrize("which", [0, 1])
def test_tampered_token_is_refused(which):
    token = sign({"email": "ana@utrgv.edu"}, SECRET, 3600, now=1000.0)
    parts = token.split(".")
    parts[which] = parts[which][:-1] + ("A" if parts[which][-1] != "A" else "B")

    assert unsign(".".join(parts), SECRET, now=1001.0) is None


def test_a_payload_swapped_in_from_another_token_is_refused():
    mine = sign({"email": "ana@utrgv.edu"}, SECRET, 3600, now=1000.0)
    theirs = sign({"email": "boss@utrgv.edu"}, SECRET, 3600, now=1000.0)

    assert unsign(theirs.split(".")[0] + "." + mine.split(".")[1], SECRET, now=1001.0) is None


def test_expired_is_refused():
    token = sign({"a": 1}, SECRET, 60, now=1000.0)

    assert unsign(token, SECRET, now=1059.0) == {"a": 1}
    assert unsign(token, SECRET, now=1060.0) is None


@pytest.mark.parametrize("garbage", ["", "x", "a.b.c", ".", "é.é", "....", "e30.e30"])
def test_garbage_is_refused(garbage):
    assert unsign(garbage, SECRET, now=1.0) is None
