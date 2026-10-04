"""W11.2 — the split screen `/split` (stage-2 "Split"; stage-1 §9; PLAN 3.14, D45, D56). I39-I42, I45."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from support import equal_split, fixture, standard_users, user
from ui import money, sel

pytestmark = pytest.mark.item(11)


def open_split(ui, handle="ada"):
    ui.log_in(handle, route="/split")
    expect(ui.el("split-submit")).to_be_visible()


def fill_split(ui, amount, handles, note=None):
    ui.fill("split-amount", amount)
    ui.fill("split-handles", handles)
    if note is not None:
        ui.fill("split-note", note)


def preview(ui) -> list[str]:
    return ui.page.eval_on_selector_all(f"{sel('split-preview')} [data-testid^='split-share-']",
                                        "els => els.map(e => e.getAttribute('data-testid') + '=' + e.textContent.trim())")


@pytest.mark.parametrize("handles,amount,minor", [
    ("ada,bob,cy", "10.00", 1_000), ("cy,bob,ada", "10.00", 1_000), ("bob,ada,cy,dee", "0.07", 7),
    ("ada, @bob , cy,", "10", 1_000), ("bob", "3.33", 333), ("dee,cy,bob,ada", "1000000", 100_000_000)])
def test_preview_follows_the_section_9_rule_before_anything_is_posted(world, ui, handles, amount, minor):
    open_split(ui)
    fill_split(ui, amount, handles)
    expect(ui.el("split-preview")).to_be_visible()
    names = [h.strip().lstrip("@") for h in handles.split(",") if h.strip()]
    shares = equal_split(minor, len(names))
    for h, s in zip(names, shares):
        expect(ui.el(f"split-share-{h}")).to_have_text(money(s))
    assert preview(ui) == [f"split-share-{h}={money(s)}" for h, s in zip(names, shares)], "in handle order"
    assert ui.writes("/splits") == [], "the preview posts nothing"


def test_the_submitted_split_matches_the_preview(world, ui):
    open_split(ui)
    fill_split(ui, "10.00", "cy,bob,ada", note="dinner")
    expect(ui.el("split-share-cy")).to_have_text(money(334))
    shown = preview(ui)
    ui.click("split-submit")
    expect(ui.el("split-success")).to_be_visible()
    ui.absent("split-error")
    sent = ui.writes("/splits")
    assert len(sent) == 1 and sent[0].body == {"amount": 1_000, "participant_handles": ["cy", "bob", "ada"],
                                               "note": "dinner"}
    reqs = {r["payer_handle"]: r["amount"] for r in world.ada.requests(direction="outgoing")}
    assert reqs == {"cy": 334, "bob": 333}
    assert shown == [f"split-share-cy={money(334)}", f"split-share-bob={money(333)}", f"split-share-ada={money(333)}"]
    ui.shot("split", "success")


def test_preview_in_other_currencies(svc, ui):
    svc.must_reset(fixture(standard_users(), currency="JPY"))
    open_split(ui)
    fill_split(ui, "10", "ada,bob,cy")
    expect(ui.el("split-share-ada")).to_have_text("4 JPY")
    expect(ui.el("split-share-bob")).to_have_text("3 JPY")


def test_unchanged_resubmission_creates_no_second_split(world, ui):
    open_split(ui)
    fill_split(ui, "3.00", "ada,bob")
    ui.click("split-submit")
    expect(ui.el("split-success")).to_be_visible()
    ui.click("split-submit")
    ui.page.wait_for_timeout(500)
    ui.absent("split-error")
    sent = ui.writes("/splits")
    assert len(sent) == 2 and sent[0].key == sent[1].key and sent[0].body == sent[1].body
    assert len(world.bob.requests()) == 1
    ui.fill("split-note", "second")
    ui.click("split-submit")
    expect(ui.el("split-success")).to_be_visible()
    ui.page.wait_for_timeout(300)
    assert len(world.bob.requests()) == 2


def test_unknown_handle_is_refused_by_the_server(world, ui):
    open_split(ui)
    fill_split(ui, "10.00", "ada,nobody")
    ui.click("split-submit")
    expect(ui.el("split-error")).to_be_visible()
    assert len(ui.writes("/splits")) == 1
    ui.absent("split-success")
    ui.shot("split", "refused")


@pytest.mark.parametrize("amount,handles", [("abc", "ada,bob"), ("10.001", "ada,bob"), ("0", "ada,bob"), ("", "ada,bob"),
                                            ("10.00", "ada,bob,ada"), ("10.00", "bob,@bob"), ("10.00", ""), ("10.00", " , ,"),
                                            ("10.00", ",".join(f"h{i}" for i in range(201)))],
                         ids=["letters", "three places", "zero", "empty amount", "repeat", "repeat with @",
                              "no handles", "only commas", "201 handles"])
def test_invalid_split_shows_split_error_and_sends_nothing(world, ui, amount, handles):
    open_split(ui)
    fill_split(ui, amount, handles)
    expect(ui.el("split-submit")).to_be_enabled()
    ui.click("split-submit")
    expect(ui.el("split-error")).to_be_visible()
    ui.page.wait_for_timeout(300)
    assert ui.writes("/splits") == []


def test_two_hundred_handles_preview(svc, ui):
    users = [user("ada", 0)] + [user(f"p{i:03d}", 0) for i in range(199)]
    svc.reset(fixture(users), track=False)
    open_split(ui)
    fill_split(ui, "2.00", ",".join(u["handle"] for u in users))
    expect(ui.el("split-share-ada")).to_have_text(money(1))
    expect(ui.el("split-share-p198")).to_have_text(money(1))


@pytest.mark.parametrize("how", ["abort-after", "empty-after"])
def test_lost_split_response_is_uncertain_and_retry_creates_one(world, ui, how):
    """W11.2, W10.3 (plan d29e313: an empty 201 after commit is unknown too)."""
    open_split(ui)
    ui.fault("/splits", "POST", how)
    fill_split(ui, "3.00", "ada,bob")
    ui.click("split-submit")
    expect(ui.el("split-uncertain")).to_be_visible()
    ui.absent("split-error")
    ui.absent("split-success")
    if how == "abort-after":
        ui.shot("split", "uncertain")
    ui.click("split-submit")
    expect(ui.el("split-success")).to_be_visible()
    ui.absent("split-uncertain")
    assert len(world.bob.requests()) == 1
    sent = ui.writes("/splits")
    assert len(sent) == 2 and sent[0].key == sent[1].key and sent[0].body == sent[1].body
    assert not ui.page_errors, f"uncaught errors in the page: {ui.page_errors}"
