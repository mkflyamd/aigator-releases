import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web" / "skills" / "m365-teams" / "scripts"))

from transcript_vtt import parse_vtt, Cue

SAMPLE = """WEBVTT

00:00:00.000 --> 00:00:05.000
<v Alice Smith>Welcome to the planning sync.</v>

00:00:05.000 --> 00:00:12.000
<v Bob Jones>Thanks. Let's start with Q3 priorities.</v>

00:00:12.000 --> 00:00:20.000
<v Alice Smith>Right. First item is the migration timeline.</v>
"""

def test_parse_vtt_basic():
    cues = parse_vtt(SAMPLE)
    assert len(cues) == 3
    assert cues[0].speaker == "Alice Smith"
    assert cues[0].start_sec == 0.0
    assert cues[0].end_sec == 5.0
    assert "Welcome" in cues[0].text
    assert cues[1].speaker == "Bob Jones"
    assert cues[2].speaker == "Alice Smith"

def test_parse_vtt_empty():
    assert parse_vtt("WEBVTT\n\n") == []

def test_parse_vtt_no_speaker_tag():
    text = "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nUnattributed line\n"
    cues = parse_vtt(text)
    assert len(cues) == 1
    assert cues[0].speaker == ""
    assert cues[0].text == "Unattributed line"

def test_parse_vtt_unpadded_timestamps():
    # Legacy Teams recordings (pre-2025 fix) use unpadded h/m/s.
    text = "WEBVTT\n\n0:0:0.000 --> 0:0:5.000\n<v Alice>Hi.</v>\n"
    cues = parse_vtt(text)
    assert len(cues) == 1
    assert cues[0].start_sec == 0.0
    assert cues[0].end_sec == 5.0
    assert cues[0].speaker == "Alice"

def test_parse_vtt_speaker_without_closing_tag():
    # Teams Graph VTT often omits the closing </v> per WebVTT spec.
    text = "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\n<v Bob Jones>Hello there\n"
    cues = parse_vtt(text)
    assert len(cues) == 1
    assert cues[0].speaker == "Bob Jones"
    assert "Hello there" in cues[0].text
    assert "<v" not in cues[0].text


from transcript_vtt import build_header, slice_range, filter_speaker, search_cues

def test_build_header():
    cues = parse_vtt(SAMPLE)
    h = build_header(cues, preview_seconds=90)
    assert h["duration_sec"] == 20
    assert h["cue_count"] == 3
    assert h["speakers"]["Alice Smith"]["cue_count"] == 2
    assert h["speakers"]["Bob Jones"]["cue_count"] == 1
    assert "preview" in h
    assert "Welcome" in h["preview"]

def test_slice_range_inclusive_overlap():
    cues = parse_vtt(SAMPLE)
    sliced = slice_range(cues, 4, 13)
    assert len(sliced) == 3
    bounded = slice_range(cues, 6, 11)
    assert len(bounded) == 1
    assert bounded[0].speaker == "Bob Jones"

def test_filter_speaker_case_insensitive():
    cues = parse_vtt(SAMPLE)
    alice = filter_speaker(cues, "alice")
    assert len(alice) == 2
    assert all(c.speaker == "Alice Smith" for c in alice)

def test_search_cues_returns_context():
    cues = parse_vtt(SAMPLE)
    hits = search_cues(cues, "migration", context_sec=30, max_results=5)
    assert len(hits) == 1
    assert hits[0]["match_index"] == 2
    assert len(hits[0]["context"]) >= 1
