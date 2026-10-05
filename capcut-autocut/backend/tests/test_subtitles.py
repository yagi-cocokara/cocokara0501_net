from app.exporters import subtitles

TRANSCRIPT = [{"start": 0.0, "end": 4.0, "text": "えーこんにちは皆さん", "words": [
    {"start": 0.0, "end": 0.5, "text": "えー"},
    {"start": 1.0, "end": 2.0, "text": "こんにちは"},
    {"start": 2.0, "end": 3.0, "text": "皆さん"},
]}]


def test_cut_words_are_removed_and_times_shifted():
    cues = subtitles.caption_cues(TRANSCRIPT, keeps=[(0.9, 4.0)])
    assert cues == [{"start": 0.1, "end": 2.1, "text": "こんにちは皆さん"}]
    assert subtitles.to_srt(cues).startswith("1\n00:00:00,100 --> 00:00:02,100\nこんにちは皆さん\n")
