#!/usr/bin/env python3
"""
Standalone script: raw meeting transcript -> formatted Markdown notes.

No imports from app/ or ai_notes/. Prompts are loaded from .txt files
in the same directory as this script.

Usage:
  python transcript_to_md.py --input ../transcription/predicted_transcription.txt
  python transcript_to_md.py --input transcript.txt --output notes.md
  python transcript_to_md.py --input transcript.txt --model gemini-3.1-flash-lite

Requires GEMINI_API_KEY in the environment or in a .env file (this folder or parent).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_SYSTEM_PROMPT = SCRIPT_DIR / "system_prompt.txt"
DEFAULT_DEV_PROMPT = SCRIPT_DIR / "dev_prompt.txt"


def load_env() -> None:
    """Load .env from script dir, then intelligence-system root if present."""
    load_dotenv(SCRIPT_DIR / ".env")
    load_dotenv(SCRIPT_DIR.parent / ".env")


def read_text_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def build_user_prompt(dev_template: str, transcript: str) -> str:
    if "{transcript}" not in dev_template:
        raise ValueError(
            f"Dev prompt must contain {{transcript}} placeholder: {DEFAULT_DEV_PROMPT}"
        )
    return dev_template.replace("{transcript}", transcript.strip())


def generate_markdown(
    *,
    transcript: str,
    system_prompt: str,
    dev_prompt: str,
    model: str,
    api_key: str,
) -> str:
    client = genai.Client(api_key=api_key)
    user_prompt = build_user_prompt(dev_prompt, transcript)

    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2,
        ),
    )

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Model returned empty Markdown output.")

    # Strip accidental full-document fences if the model adds them.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    return text


def default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_notes.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a raw meeting transcript into formatted Markdown notes."
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        type=Path,
        help="Path to raw transcript .txt file",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Path for output .md file (default: <input_stem>_notes.md)",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=os.getenv("TRANSCRIPT_TO_MD_MODEL", DEFAULT_MODEL),
        help=f"Gemini model id (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--system-prompt",
        type=Path,
        default=DEFAULT_SYSTEM_PROMPT,
        help="Path to system prompt .txt",
    )
    parser.add_argument(
        "--dev-prompt",
        type=Path,
        default=DEFAULT_DEV_PROMPT,
        help="Path to dev/user prompt template .txt (must include {transcript})",
    )
    return parser.parse_args()


def main() -> int:
    load_env()
    args = parse_args()

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print(
            "Error: GEMINI_API_KEY is not set. Add it to .env or export it.",
            file=sys.stderr,
        )
        return 1

    input_path = args.input.resolve()
    if not input_path.is_file():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return 1

    output_path = (args.output or default_output_path(input_path)).resolve()

    try:
        system_prompt = read_text_file(args.system_prompt.resolve())
        dev_prompt = read_text_file(args.dev_prompt.resolve())
        transcript = input_path.read_text(encoding="utf-8")

        print(f"Model:     {args.model}")
        print(f"Input:     {input_path}")
        print(f"Transcript length: {len(transcript):,} chars")
        print("Generating Markdown...")

        markdown = generate_markdown(
            transcript=transcript,
            system_prompt=system_prompt,
            dev_prompt=dev_prompt,
            model=args.model,
            api_key=api_key,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown + "\n", encoding="utf-8")

        print(f"Output:    {output_path}")
        print(f"Lines:     {len(markdown.splitlines())}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
