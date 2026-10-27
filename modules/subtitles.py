import math
from pathlib import Path


def _format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,110,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,1,8,6,5,60,60,500,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass_subtitles(
    scene_text: str,
    audio_duration: float,
    scene_no: int,
    output_path: str,
    chunk_size: int = 4,
    highlight_color: str = "&H0000FFFF",  # Default yellow
) -> str:
    clean_text = scene_text.replace("'", "").replace('"', "").replace("\n", " ").strip()
    words = clean_text.split()
    if not words:
        words = ["..."]

    total_words = len(words)
    word_duration = audio_duration / max(total_words, 1)

    events = []
    current_time = 0.0

    # Process in chunks of N words
    for i in range(0, total_words, chunk_size):
        chunk_words = words[i : i + chunk_size]
        chunk_len = len(chunk_words)
        
        # Base format for unhighlighted words: White color
        base_color = "&H00FFFFFF"

        # Generate an event for each word being highlighted in the chunk
        for j in range(chunk_len):
            start_time = current_time + (j * word_duration)
            # Make sure the last word spans to the exact end of the chunk duration
            if j == chunk_len - 1:
                end_time = current_time + (chunk_len * word_duration)
            else:
                end_time = start_time + word_duration

            # Build the text for this exact sub-event
            display_words = []
            for k, w in enumerate(chunk_words):
                w_upper = w.upper()
                if k == j:
                    # Highlighted word: color + scale pop + bold
                    display_words.append(f"{{\\c{highlight_color}}}{{\\fscx115\\fscy115}}{w_upper}{{\\fscx100\\fscy100}}{{\\c{base_color}}}")
                else:
                    # Normal word
                    display_words.append(w_upper)
            
            text_line = " ".join(display_words)
            events.append(
                f"Dialogue: 0,{_format_ass_time(start_time)},{_format_ass_time(end_time)},Default,,0,0,0,,{text_line}"
            )

        current_time += chunk_len * word_duration

    content = ASS_HEADER + "\n".join(events) + "\n"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(content, encoding="utf-8")
    return output_path
