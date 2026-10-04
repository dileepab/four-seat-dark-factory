"""PLAN 3.13 (D103) — the stage-2 UI after refunds and batches: the wallet shows the current corrected `total`,
`available` and `held` from `GET /me`, and the feed shows a refund as the payment it is (stage-2 "Activity feed").
I39, I41, I66, I77.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from support import batch_item, expect as expect_status
from test_w10_wallet import feed_children, open_wallet
from ui import money


@pytest.mark.item(19)
def test_a_refund_is_a_feed_payment_and_the_wallet_counts_it(world, ui):
    p = expect_status(world.ada.pay("bob", 1_000, note="dinner", visibility="private"), 201)
    r = expect_status(world.bob.refund(p["payment_id"], 300), 201)
    expect_status(world.ada.authorize("cy", 200), 201)
    open_wallet(ui)
    ui.wallet(9_300, held=200)
    rid = r["payment_id"]
    expect(ui.el(f"activity-item-{rid}")).to_have_attribute("data-visibility", "private")
    expect(ui.el(f"activity-amount-{rid}")).to_have_text(money(300))
    parties = ui.text(f"activity-parties-{rid}")
    assert "bob" in parties and "ada" in parties
    expect(ui.el(f"activity-note-{rid}")).to_have_text("dinner")
    order = [t for t in feed_children(ui) if t and t.startswith("activity-item-")]
    assert order == [f"activity-item-{x['payment_id']}" for x in world.ada.feed()], "the API feed order, newest first"
    ui.shot("wallet", "refunded")


@pytest.mark.item(20)
def test_after_a_batch_the_wallet_shows_the_corrected_total_and_the_feed_the_original(world, ui):
    p = expect_status(world.ada.pay("bob", 1_000, note="rent"), 201)
    expect_status(world.ada.batch([batch_item(p, 1, 600)]), 201)
    open_wallet(ui)
    ui.wallet(9_400)
    expect(ui.el(f"activity-amount-{p['payment_id']}")).to_have_text(money(1_000))
    ui.shot("wallet", "batch-corrected")
