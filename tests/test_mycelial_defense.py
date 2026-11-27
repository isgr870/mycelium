from core.mycelial_defense import MycelialDefense


def test_quarantine_escalates_and_reroutes_around_bad_peer():
    defense = MycelialDefense(strike_threshold=2, base_quarantine_seconds=60.0)
    t0 = 1_700_000_000.0

    defense.record_violation("peer-bad", "invalid_hmac", now=t0)
    assert not defense.is_quarantined("peer-bad", now=t0 + 1)

    defense.record_violation("peer-bad", "replay_nonce", now=t0 + 2)
    assert defense.is_quarantined("peer-bad", now=t0 + 30)

    routed = defense.route_peers(["peer-bad", "peer-ug-1", "peer-us-1"], now=t0 + 30)
    assert routed == ["peer-ug-1", "peer-us-1"]

    # After quarantine window expires, peer can participate again
    assert not defense.is_quarantined("peer-bad", now=t0 + 65)
    assert defense.route_peers(["peer-bad", "peer-ug-1"], now=t0 + 65) == ["peer-bad", "peer-ug-1"]


def test_healthy_streak_heals_strike_count():
    defense = MycelialDefense(strike_threshold=3, recovery_healthy_streak=2)
    defense.record_violation("peer-1", "clock_skew", now=100.0)
    assert defense._get_or_create("peer-1").strikes == 1

    defense.record_healthy("peer-1")
    assert defense._get_or_create("peer-1").strikes == 1
    defense.record_healthy("peer-1")
    assert defense._get_or_create("peer-1").strikes == 0
