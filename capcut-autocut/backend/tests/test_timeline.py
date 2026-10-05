from app import timeline


def test_silence_cuts_keep_padding_and_trim_edges():
    cuts = timeline.silence_cuts([(0.0, 1.0), (3.0, 4.0), (9.0, 10.0)], padding=0.1, duration=10.0)
    assert [(c["start"], c["end"]) for c in cuts] == [(0.0, 0.9), (3.1, 3.9), (9.1, 10.0)]


def test_keep_segments_merges_overlaps_and_skips_disabled():
    cuts = [
        timeline.make_cut(1, 2, "silence", "silence", "", 1),
        timeline.make_cut(1.5, 3, "ai", "filler", "", 0.9),
        timeline.make_cut(5, 6, "ai", "retake", "", 0.3, enabled=False),
    ]
    assert timeline.keep_segments(cuts, 10) == [(0.0, 1.0), (3.0, 10.0)]


def test_keep_segments_drops_tiny_fragments():
    cuts = [timeline.make_cut(1, 2, "manual", "manual", "", 1), timeline.make_cut(2.05, 3, "manual", "manual", "", 1)]
    assert timeline.keep_segments(cuts, 4) == [(0.0, 1.0), (3.0, 4.0)]


def test_remap():
    keeps = [(0.0, 1.0), (3.0, 5.0)]
    assert timeline.remap(0.5, keeps) == 0.5
    assert timeline.remap(2.0, keeps) is None
    assert timeline.remap(4.0, keeps) == 2.0
    assert timeline.remap_range(0.5, 4.0, keeps) == (0.5, 2.0)
