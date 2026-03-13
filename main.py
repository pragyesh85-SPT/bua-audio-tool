import os
import re
import uuid
import zipfile
import tempfile
import shutil
from pathlib import Path
from typing import List

import ffmpeg
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI()

# --- Models ---

class VideoInfoRequest(BaseModel):
    url: str

class Segment(BaseModel):
    start: str  # e.g. "1:30" or "0:01:30"
    end: str
    label: str = ""

class ProcessRequest(BaseModel):
    url: str
    segments: List[Segment]

class MergeRequest(BaseModel):
    url: str
    segments: List[Segment]


# --- Helpers ---

def parse_time(t: str) -> float:
    """Convert MM:SS or HH:MM:SS string to seconds."""
    t = t.strip()
    parts = t.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    else:
        return float(t)


def safe_filename(name: str) -> str:
    """Strip unsafe characters from a filename."""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip()[:80] or "segment"


def download_audio(url: str, out_dir: str) -> str:
    """Download best audio from YouTube, return path to downloaded file."""
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(out_dir, "source.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Find the downloaded mp3
    for f in Path(out_dir).iterdir():
        if f.suffix == ".mp3":
            return str(f)
    raise FileNotFoundError("Audio download failed — no MP3 found.")


def cut_segment(source_mp3: str, start: float, end: float, out_path: str):
    """Cut a segment from source MP3 using ffmpeg."""
    duration = end - start
    (
        ffmpeg
        .input(source_mp3, ss=start, t=duration)
        .output(out_path, acodec="libmp3lame", audio_bitrate="192k")
        .overwrite_output()
        .run(quiet=True)
    )


# --- Routes ---

@app.post("/api/info")
async def video_info(req: VideoInfoRequest):
    ydl_opts = {"quiet": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)
        duration = info.get("duration", 0)
        minutes, seconds = divmod(int(duration), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            duration_str = f"{minutes}:{seconds:02d}"
        return {
            "title": info.get("title", "Unknown"),
            "thumbnail": info.get("thumbnail", ""),
            "duration": duration_str,
            "duration_seconds": duration,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/process")
async def process(req: ProcessRequest):
    if not req.segments:
        raise HTTPException(status_code=400, detail="No segments provided.")

    tmp_dir = tempfile.mkdtemp()
    try:
        source_mp3 = download_audio(req.url, tmp_dir)

        zip_path = os.path.join(tmp_dir, "segments.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            for i, seg in enumerate(req.segments, 1):
                start = parse_time(seg.start)
                end = parse_time(seg.end)
                if end <= start:
                    raise HTTPException(status_code=400, detail=f"Segment {i}: end must be after start.")
                label = safe_filename(seg.label) or f"segment_{i:02d}"
                out_name = f"{i:02d}_{label}.mp3"
                out_path = os.path.join(tmp_dir, out_name)
                cut_segment(source_mp3, start, end, out_path)
                zf.write(out_path, out_name)

        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="bua_audio_cuts.zip",
            background=None,
        )
    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/merge")
async def merge(req: MergeRequest):
    if not req.segments:
        raise HTTPException(status_code=400, detail="No segments provided.")

    tmp_dir = tempfile.mkdtemp()
    try:
        source_mp3 = download_audio(req.url, tmp_dir)

        segment_paths = []
        for i, seg in enumerate(req.segments, 1):
            start = parse_time(seg.start)
            end = parse_time(seg.end)
            if end <= start:
                raise HTTPException(status_code=400, detail=f"Segment {i}: end must be after start.")
            out_path = os.path.join(tmp_dir, f"seg_{i:03d}.mp3")
            cut_segment(source_mp3, start, end, out_path)
            segment_paths.append(out_path)

        # Write concat list file
        list_file = os.path.join(tmp_dir, "concat.txt")
        with open(list_file, "w") as f:
            for p in segment_paths:
                f.write(f"file '{p}'\n")

        merged_path = os.path.join(tmp_dir, "merged.mp3")
        (
            ffmpeg
            .input(list_file, format="concat", safe=0)
            .output(merged_path, acodec="libmp3lame", audio_bitrate="192k")
            .overwrite_output()
            .run(quiet=True)
        )

        return FileResponse(
            merged_path,
            media_type="audio/mpeg",
            filename="bua_merged.mp3",
        )
    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))


# Serve static files (must be after API routes)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
