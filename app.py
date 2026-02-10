import streamlit as st
import yt_dlp
from pydub import AudioSegment
import os
from pathlib import Path
import re

# --- Config ---
st.set_page_config(page_title="Audio Tool", page_icon="🎵")
TEMP_DIR = Path("temp_downloads")
TEMP_DIR.mkdir(exist_ok=True)

# --- Helpers ---
def cleanup_files(files):
    """Removes temporary files."""
    for f in files:
        try:
            if f.exists():
                os.remove(f)
        except Exception as e:
            st.warning(f"Could not remove {f}: {e}")

def parse_time_str(time_str):
    """Parses 'MM:SS' or 'SS' into milliseconds."""
    if not time_str:
        return 0
    try:
        parts = list(map(int, re.split('[:.]', time_str)))
        if len(parts) == 1:
            return parts[0] * 1000
        elif len(parts) == 2:
            return (parts[0] * 60 + parts[1]) * 1000
        elif len(parts) == 3:
             return (parts[0] * 3600 + parts[1] * 60 + parts[2]) * 1000
    except ValueError:
        return 0
    return 0

def download_audio(url, output_stem):
    """Downloads audio via yt-dlp."""
    output_path = TEMP_DIR / f"{output_stem}.mp3"
    # Clean up existing if any
    if output_path.exists():
        os.remove(output_path)
        
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(TEMP_DIR / f"{output_stem}.%(ext)s"),
        'quiet': True,
        'no_warnings': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        # Use a real browser User-Agent to avoid bot detection
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        # Force specific clients that are less likely to be blocked
        'extractor_args': {
            'youtube': {
                'player_client': ['android_web', 'web']
            }
        }
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
        
    # yt-dlp might produce file with .mp3 extension directly
    if output_path.exists():
        return output_path
    
    return None

def process_segment(audio_path, start_ms, end_ms, fade_in, fade_out):
    """Loads, trims, and fades audio using pydub."""
    try:
        audio = AudioSegment.from_file(str(audio_path))
    except Exception as e:
        st.error(f"Error loading audio: {e}")
        return None

    # Trim
    if end_ms > 0:
        segment = audio[start_ms:end_ms]
    else:
        segment = audio[start_ms:]

    # Fade
    if fade_in:
        segment = segment.fade_in(3000)
    if fade_out:
        segment = segment.fade_out(3000)
        
    return segment

# --- UI ---
st.title("🎵 Bua Audio Tool")

st.markdown("### Track 1")
url1 = st.text_input("YouTube URL 1", key="url1")
col1, col2 = st.columns(2)
start1_str = col1.text_input("Start (MM:SS)", "0:00", key="s1")
end1_str = col2.text_input("End (MM:SS) - Leave empty for full", "", key="e1")
fade1_in = col1.checkbox("Fade In (3s)", key="f1i")
fade1_out = col2.checkbox("Fade Out (3s)", key="f1o")

st.markdown("---")
add_second_track = st.checkbox("Add Second Track (Overlay)")
url2 = ""
start2_str = "0:00"
end2_str = ""
fade2_in = False
fade2_out = False

if add_second_track:
    st.markdown("### Track 2")
    url2 = st.text_input("YouTube URL 2", key="url2")
    col3, col4 = st.columns(2)
    start2_str = col3.text_input("Start (MM:SS)", "0:00", key="s2")
    end2_str = col4.text_input("End (MM:SS)", "", key="e2")
    fade2_in = col3.checkbox("Fade In (3s)", key="f2i")
    fade2_out = col4.checkbox("Fade Out (3s)", key="f2o")

if st.button("Process Audio"):
    if not url1:
        st.error("Please provide at least URL 1")
    else:
        status_text = st.empty()
        status_text.text("Downloading Track 1...")
        
        path1 = download_audio(url1, "track1")
        if not path1:
            st.error("Failed to download Track 1")
            st.stop()
            
        start1 = parse_time_str(start1_str)
        end1 = parse_time_str(end1_str)
        
        status_text.text("Processing Track 1...")
        seg1 = process_segment(path1, start1, end1, fade1_in, fade1_out)
        
        final_audio = seg1
        
        if add_second_track and url2:
            status_text.text("Downloading Track 2...")
            path2 = download_audio(url2, "track2")
            if path2:
                start2 = parse_time_str(start2_str)
                end2 = parse_time_str(end2_str)
                
                status_text.text("Processing Track 2...")
                seg2 = process_segment(path2, start2, end2, fade2_in, fade2_out)
                
                if seg2:
                    status_text.text("Merging Tracks...")
                    # Overlay track 2 on track 1
                    final_audio = seg1.overlay(seg2)
            else:
                st.warning("Failed to download Track 2, skipping merge.")

        output_filename = "processed_audio.mp3"
        output_path = TEMP_DIR / output_filename
        
        status_text.text("Exporting...")
        final_audio.export(output_path, format="mp3")
        
        status_text.text("Done!")
        st.audio(str(output_path), format="audio/mp3")
        
        with open(output_path, "rb") as f:
            st.download_button("Download MP3", f, file_name="bua_audio.mp3")
            
        # Cleanup is tricky in Streamlit as re-runs might need files, 
        # but for this script we can clean up source files at least
        cleanup_files([path1, TEMP_DIR/"track2.mp3"] if add_second_track and url2 else [path1])
