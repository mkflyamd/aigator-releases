#!/usr/bin/env python3
"""Read Teams meeting transcripts via the beta drive-item path.

Recordings are identified by (driveId, itemId) — resolved either from a meeting
chat (scans for the RichText/Media_CallRecording attachment) or passed directly.

Usage:
    python3 read_meeting_transcript.py resolve --chat-id <id>
    python3 read_meeting_transcript.py list --drive-id <d> --item-id <i>
    python3 read_meeting_transcript.py header --drive-id <d> --item-id <i> --transcript-id <tid>
    python3 read_meeting_transcript.py range  --drive-id <d> --item-id <i> --transcript-id <tid> --start-min 0 --end-min 20
    python3 read_meeting_transcript.py search --drive-id <d> --item-id <i> --transcript-id <tid> --q "pricing"
    python3 read_meeting_transcript.py speaker --drive-id <d> --item-id <i> --transcript-id <tid> --name "Alice"
    python3 read_meeting_transcript.py full   --drive-id <d> --item-id <i> --transcript-id <tid>
"""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import transcript_config, transcript_vtt, transcript_cache, transcript_beta, transcript_recording


def _load(drive_id, item_id, transcript_id):
    text = transcript_cache.read(transcript_id)
    if text is None:
        text = transcript_beta.fetch_transcript_content(drive_id, item_id, transcript_id)
        transcript_cache.write(transcript_id, text)
    return text


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_resolve = sub.add_parser("resolve")
    sp_resolve.add_argument("--chat-id", required=True)

    for name in ("list", "header", "range", "search", "speaker", "full"):
        sp = sub.add_parser(name)
        sp.add_argument("--drive-id", required=True)
        sp.add_argument("--item-id", required=True)
        if name != "list":
            sp.add_argument("--transcript-id", required=True)
        if name == "range":
            sp.add_argument("--start-min", type=float, default=0)
            sp.add_argument("--end-min", type=float, default=60)
        if name == "search":
            sp.add_argument("--q", required=True)
            sp.add_argument("--max-results", type=int, default=5)
        if name == "speaker":
            sp.add_argument("--name", required=True)

    args = p.parse_args()

    if args.cmd == "resolve":
        info = transcript_recording.resolve_recording_from_chat(args.chat_id)
        print(json.dumps(info.__dict__ if info else None, indent=2, default=str))
        return

    if args.cmd == "list":
        items = transcript_beta.list_transcripts(args.drive_id, args.item_id)[
            : transcript_config.RECURRING_OCCURRENCES_CAP
        ]
        print(json.dumps(items, indent=2, default=str))
        return

    vtt = _load(args.drive_id, args.item_id, args.transcript_id)
    cues = transcript_vtt.parse_vtt(vtt)

    if args.cmd == "header":
        h = transcript_vtt.build_header(cues, preview_seconds=90)
        h["size_tokens_estimate"] = transcript_config.estimate_tokens_from_vtt_bytes(len(vtt.encode("utf-8")))
        print(json.dumps(h, indent=2))
    elif args.cmd == "range":
        sliced = transcript_vtt.slice_range(cues, args.start_min * 60, args.end_min * 60)
        print(transcript_vtt.cues_to_text(sliced))
    elif args.cmd == "search":
        hits = transcript_vtt.search_cues(cues, args.q, transcript_config.SEARCH_CONTEXT_SECONDS, args.max_results)
        print(json.dumps(hits, indent=2))
    elif args.cmd == "speaker":
        filt = transcript_vtt.filter_speaker(cues, args.name)
        print(transcript_vtt.cues_to_text(filt))
    elif args.cmd == "full":
        print(transcript_vtt.cues_to_text(cues))


if __name__ == "__main__":
    main()
