import os
import re
import html
import wave
import tempfile
import subprocess
from typing import List

from google.cloud import texttospeech


# ----------------------------
# Paths
# ----------------------------
INPUT_FILE = os.getenv("INPUT_FILE", "/input/input.txt")
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "/output/output.wav")

# ----------------------------
# Voice
# ----------------------------
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "en-US")
VOICE_NAME = os.getenv("VOICE_NAME", "en-US-Neural2-J")

# ----------------------------
# Audio
# ----------------------------
AUDIO_ENCODING = os.getenv("AUDIO_ENCODING", "LINEAR16").upper()
SAMPLE_RATE_HZ = int(os.getenv("SAMPLE_RATE_HZ", "24000"))

# ----------------------------
# Professor-style delivery
# ----------------------------
SPEAKING_RATE = float(os.getenv("SPEAKING_RATE", "0.88"))
PITCH = float(os.getenv("PITCH", "-1.0"))

# ----------------------------
# SSML
# ----------------------------
USE_SSML = os.getenv("USE_SSML", "true").lower() in ("1", "true", "yes", "y")
SSML_MODE = os.getenv("SSML_MODE", "auto").lower()  # auto | raw

BREAK_MS = int(os.getenv("BREAK_MS", "220"))
PARA_BREAK_MS = int(os.getenv("PARA_BREAK_MS", "420"))

PROFESSOR_PROSODY = os.getenv("PROFESSOR_PROSODY", "false").lower() in ("1", "true", "yes", "y")
PROSODY_RATE = os.getenv("PROSODY_RATE", "88%")
PROSODY_PITCH = os.getenv("PROSODY_PITCH", "-1st")

# ----------------------------
# Hard limit handling
# ----------------------------
# Google standard TTS limit: input.text or input.ssml must be <= 5000 bytes.
# We keep a safety buffer to account for any internal handling.
MAX_SSML_BYTES = int(os.getenv("MAX_SSML_BYTES", "4700"))
MAX_TEXT_BYTES = int(os.getenv("MAX_TEXT_BYTES", "4700"))  # used when USE_SSML=false


def utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


def read_text(path: str) -> str:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Input file not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def write_wav(path: str, pcm_bytes: bytes, sample_rate_hz: int) -> None:
    ensure_parent_dir(path)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate_hz)
        wf.writeframes(pcm_bytes)


def auto_text_to_ssml(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    ssml_paras = []
    for p in paragraphs:
        p = html.escape(p)

        # Sentence endings: longer pause (lecture pacing)
        p = re.sub(r"([.!?])(\s+)", rf"\1 <break time='{BREAK_MS}ms'/> ", p)

        # Commas: short clarity pause
        p = re.sub(r"(,)(\s+)", r"\1 <break time='120ms'/> ", p)

        # Colons/semicolons: longer "setup" pause
        p = re.sub(r"([:;])(\s+)", r"\1 <break time='220ms'/> ", p)

        # Em-dash / double-dash: reflective pause
        p = re.sub(r"(\u2014|--)(\s+)", r"\1 <break time='180ms'/> ", p)

        if PROFESSOR_PROSODY:
            ssml_paras.append(f"<p><prosody rate='{PROSODY_RATE}' pitch='{PROSODY_PITCH}'>{p}</prosody></p>")
        else:
            ssml_paras.append(f"<p>{p}</p>")

    joiner = f"<break time='{PARA_BREAK_MS}ms'/>"
    return "<speak>" + joiner.join(ssml_paras) + "</speak>"


def build_synthesis_input(raw: str) -> texttospeech.SynthesisInput:
    if not USE_SSML:
        return texttospeech.SynthesisInput(text=raw)

    if SSML_MODE == "raw":
        return texttospeech.SynthesisInput(ssml=raw)

    return texttospeech.SynthesisInput(ssml=auto_text_to_ssml(raw))


def ssml_bytes_for_text_chunk(text_chunk: str) -> int:
    """
    When SSML_MODE=auto, this is what we actually send.
    Chunking must keep this under MAX_SSML_BYTES.
    """
    ssml = auto_text_to_ssml(text_chunk)
    return utf8_len(ssml)


def split_text_sentence_aware(raw_text: str) -> List[str]:
    """
    SSML-aware chunking:
    - Split on paragraphs and sentences
    - Grow a chunk until the FINAL SSML bytes would exceed MAX_SSML_BYTES
    """
    txt = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not txt:
        return []

    # Sentence splitter
    sentence_split_re = re.compile(r"(?<=[.!?])\s+")

    # Keep paragraphs as soft boundaries for more natural speech
    paragraphs = [p.strip() for p in txt.split("\n\n") if p.strip()]

    chunks: List[str] = []
    current = ""

    def fits(candidate_text: str) -> bool:
        if USE_SSML and SSML_MODE == "auto":
            return ssml_bytes_for_text_chunk(candidate_text) <= MAX_SSML_BYTES
        return utf8_len(candidate_text) <= MAX_TEXT_BYTES

    def try_add(cur: str, addition: str) -> bool:
        candidate = (cur + ("\n\n" if cur else "") + addition).strip()
        if not candidate:
            return True
        if fits(candidate):
            return True
        return False

    def flush():
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for para in paragraphs:
        # If the whole paragraph can be added, do it.
        if try_add(current, para):
            current = (current + ("\n\n" if current else "") + para).strip()
            continue

        # Paragraph doesn't fit with current. Flush current and handle paragraph by sentences.
        flush()

        # If paragraph alone fits, keep it.
        if fits(para):
            current = para
            continue

        # Split paragraph into sentences
        sentences = [s.strip() for s in sentence_split_re.split(para) if s.strip()]
        sent_buf = ""

        for s in sentences:
            candidate = (sent_buf + (" " if sent_buf else "") + s).strip()

            if fits(candidate):
                sent_buf = candidate
                continue

            # sentence doesn't fit into sent_buf; flush sent_buf
            if sent_buf:
                chunks.append(sent_buf)
                sent_buf = ""

            # If single sentence still doesn't fit, split by words as last resort
            if not fits(s):
                words = s.split()
                wbuf = ""
                for w in words:
                    cand = (wbuf + (" " if wbuf else "") + w).strip()
                    if fits(cand):
                        wbuf = cand
                    else:
                        if wbuf:
                            chunks.append(wbuf)
                        wbuf = w
                if wbuf:
                    chunks.append(wbuf)
            else:
                sent_buf = s

        if sent_buf:
            chunks.append(sent_buf)

    flush()

    # Safety: verify each chunk fits (helps debugging)
    for i, c in enumerate(chunks, 1):
        if USE_SSML and SSML_MODE == "auto":
            b = ssml_bytes_for_text_chunk(c)
            if b > MAX_SSML_BYTES:
                raise RuntimeError(f"Internal error: chunk {i} SSML bytes={b} exceeds MAX_SSML_BYTES={MAX_SSML_BYTES}")
        else:
            b = utf8_len(c)
            if b > MAX_TEXT_BYTES:
                raise RuntimeError(f"Internal error: chunk {i} text bytes={b} exceeds MAX_TEXT_BYTES={MAX_TEXT_BYTES}")

    return chunks


def get_encoding() -> texttospeech.AudioEncoding:
    if AUDIO_ENCODING == "MP3":
        return texttospeech.AudioEncoding.MP3
    if AUDIO_ENCODING == "OGG_OPUS":
        return texttospeech.AudioEncoding.OGG_OPUS
    return texttospeech.AudioEncoding.LINEAR16


def synthesize_one(
    client: texttospeech.TextToSpeechClient,
    voice: texttospeech.VoiceSelectionParams,
    audio_config: texttospeech.AudioConfig,
    chunk_text: str,
) -> bytes:
    synthesis_input = build_synthesis_input(chunk_text)
    return client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    ).audio_content


def ffmpeg_concat_audio(files: List[str], output_path: str) -> None:
    ensure_parent_dir(output_path)
    with tempfile.TemporaryDirectory() as td:
        list_path = os.path.join(td, "concat_list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for fp in files:
                f.write(f"file '{fp}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            output_path,
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                "ffmpeg concat failed.\n"
                f"Command: {' '.join(cmd)}\n"
                f"stderr:\n{proc.stderr}"
            )


def main() -> None:
    raw = read_text(INPUT_FILE)
    if not raw:
        raise ValueError("Input text is empty.")

    # Raw SSML is not chunked here (SSML-aware splitting is more complex).
    if USE_SSML and SSML_MODE == "raw":
        if utf8_len(raw) > 5000:
            raise ValueError(
                "SSML_MODE=raw but your SSML is over the ~5000-byte Google limit. "
                "Switch to SSML_MODE=auto (recommended), or shorten the SSML."
            )

    client = texttospeech.TextToSpeechClient()

    voice = texttospeech.VoiceSelectionParams(
        language_code=LANGUAGE_CODE,
        name=VOICE_NAME,
    )

    encoding = get_encoding()

    audio_config = texttospeech.AudioConfig(
        audio_encoding=encoding,
        speaking_rate=SPEAKING_RATE,
        pitch=PITCH,
        sample_rate_hertz=SAMPLE_RATE_HZ if encoding == texttospeech.AudioEncoding.LINEAR16 else None,
    )

    chunks = split_text_sentence_aware(raw)
    if not chunks:
        raise ValueError("Nothing to synthesize after splitting (input may be empty).")

    if USE_SSML and SSML_MODE == "auto":
        debug_sizes = [ssml_bytes_for_text_chunk(c) for c in chunks[:3]]
        print(f"Split into {len(chunks)} chunk(s) (MAX_SSML_BYTES={MAX_SSML_BYTES}); first sizes={debug_sizes}")
    else:
        debug_sizes = [utf8_len(c) for c in chunks[:3]]
        print(f"Split into {len(chunks)} chunk(s) (MAX_TEXT_BYTES={MAX_TEXT_BYTES}); first sizes={debug_sizes}")

    if encoding == texttospeech.AudioEncoding.LINEAR16:
        combined_pcm = b""
        for i, chunk in enumerate(chunks, 1):
            print(f"Processing chunk {i}/{len(chunks)}")
            combined_pcm += synthesize_one(client, voice, audio_config, chunk)

        write_wav(OUTPUT_FILE, combined_pcm, SAMPLE_RATE_HZ)
        print(f"Done! Audio saved to {OUTPUT_FILE}")
        return

    # MP3 / OGG_OPUS: stitch with ffmpeg
    with tempfile.TemporaryDirectory() as td:
        ext = "mp3" if encoding == texttospeech.AudioEncoding.MP3 else "ogg"
        part_files: List[str] = []

        for i, chunk in enumerate(chunks, 1):
            print(f"Processing chunk {i}/{len(chunks)}")
            audio_bytes = synthesize_one(client, voice, audio_config, chunk)
            part_path = os.path.join(td, f"part_{i:04d}.{ext}")
            with open(part_path, "wb") as f:
                f.write(audio_bytes)
            part_files.append(part_path)

        ffmpeg_concat_audio(part_files, OUTPUT_FILE)
        print(f"Done! Audio saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
