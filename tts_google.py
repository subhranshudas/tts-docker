import os
from google.cloud import texttospeech

INPUT_FILE = os.getenv("INPUT_FILE", "/input/input.txt")
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "/output/output.wav")

LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "en-US")
VOICE_NAME = os.getenv("VOICE_NAME", "en-US-Neural2-J")

# LINEAR16 -> WAV-like PCM (we'll write a proper WAV container below)
# MP3 -> mp3 bytes
AUDIO_ENCODING = os.getenv("AUDIO_ENCODING", "LINEAR16").upper()

SPEAKING_RATE = float(os.getenv("SPEAKING_RATE", "1.0"))
PITCH = float(os.getenv("PITCH", "0.0"))
SAMPLE_RATE_HZ = int(os.getenv("SAMPLE_RATE_HZ", "24000"))  # common for Neural voices

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
    """
    Google returns raw PCM for LINEAR16.
    Wrap it in a WAV container so players can read it.
    """
    import wave
    import io

    ensure_parent_dir(path)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)          # mono
        wf.setsampwidth(2)          # 16-bit
        wf.setframerate(sample_rate_hz)
        wf.writeframes(pcm_bytes)

def main():
    text = read_text(INPUT_FILE)
    if not text:
        raise ValueError("Input text is empty.")

    client = texttospeech.TextToSpeechClient()

    synthesis_input = texttospeech.SynthesisInput(text=text)

    voice = texttospeech.VoiceSelectionParams(
        language_code=LANGUAGE_CODE,
        name=VOICE_NAME,
    )

    if AUDIO_ENCODING == "MP3":
        encoding = texttospeech.AudioEncoding.MP3
    elif AUDIO_ENCODING == "OGG_OPUS":
        encoding = texttospeech.AudioEncoding.OGG_OPUS
    else:
        # default to LINEAR16 for wav output
        encoding = texttospeech.AudioEncoding.LINEAR16

    audio_config = texttospeech.AudioConfig(
        audio_encoding=encoding,
        speaking_rate=SPEAKING_RATE,
        pitch=PITCH,
        sample_rate_hertz=SAMPLE_RATE_HZ if encoding == texttospeech.AudioEncoding.LINEAR16 else None,
    )

    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )

    if encoding == texttospeech.AudioEncoding.LINEAR16:
        # If OUTPUT_FILE ends with .mp3 but encoding is LINEAR16, still write wav container.
        write_wav(OUTPUT_FILE, response.audio_content, SAMPLE_RATE_HZ)
    else:
        ensure_parent_dir(OUTPUT_FILE)
        with open(OUTPUT_FILE, "wb") as out:
            out.write(response.audio_content)

    print(f"Done! Audio saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
