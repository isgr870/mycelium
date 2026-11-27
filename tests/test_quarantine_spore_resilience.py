from core.mycelial_defense import MycelialDefense
from core.resilience_queue import enqueue_outbound, queue_depth
from core.spore_vault_sync import store_spore


def test_spore_and_queue_resilience_under_peer_quarantine(monkeypatch, tmp_path):
    monkeypatch.setattr("core.spore_vault_sync.DB_PATH", str(tmp_path / "spore_quarantine.db"))
    monkeypatch.setattr("core.resilience_queue.DB_PATH", str(tmp_path / "spore_quarantine.db"))

    defense = MycelialDefense(
        strike_threshold=2,
        base_quarantine_seconds=60.0,
        recovery_healthy_streak=2,
    )

    bad_peer = "https://bad-peer.mesh"
    healthy_peer = "https://healthy-asia.mesh"

    defense.record_violation(bad_peer, "invalid_hmac", now=100.0)
    defense.record_violation(bad_peer, "replay_nonce", now=101.0)

    assert defense.route_peers([bad_peer, healthy_peer], now=105.0) == [healthy_peer]

    spore = store_spore(
        "defense-alert",
        {"region": "ug", "msg": "quarantine-active"},
        author_node="node-ug-01",
    )
    assert isinstance(spore, dict) and len(spore) > 0

    enqueue_outbound(
        bad_peer,
        "/mesh/spores/push",
        {"spores": [spore]},
    )
    assert queue_depth() == 1

    # Once quarantine window passes and healthy streak completes, peer is eligible again
    assert defense.is_quarantined(bad_peer, now=200.0) is False
    defense.record_healthy(bad_peer)
    defense.record_healthy(bad_peer)
    assert defense.route_peers([bad_peer, healthy_peer], now=200.0) == [
        bad_peer,
        healthy_peer,
    ]
