"""FFmpeg-Mastering: fertige 9:16-Filme aus Einzel-Shots + Master-Audio.

Was hier passiert
-----------------
1. **Bild**: Die gerenderten Shots werden frame-exakt an ihre Position gelegt
   (kein Zeitsprung, kein doppeltes Bild), auf 1080x1920 normalisiert und
   zusammengefuegt. Jeder Shot wird auf seine exakte Framezahl getrimmt.
2. **Ton**: Die in :mod:`1_system.audio.sound_design` gemasterte Spur wird
   uebernommen (Sprache + Musik + SFX + Loudness-Normalisierung).
3. **Untertitel**: Nur wenn ``subtitles: true`` - dann werden die wortgenauen
   TikTok-Untertitel mit libass eingebrannt (inkl. Font-Ordner).
4. **Beigaben**: Storyboard-PNG (jeder Shot einmal) und Render-Bericht.

Die FFmpeg-Argumente werden in :func:`build_ffmpeg_command` als reine Daten
zusammengebaut - so laesst sich der Schnitt ohne FFmpeg testen.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import yaml

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

font_manager = importlib.import_module("1_system.tools.font_manager")

WIDTH, HEIGHT, FPS = 1080, 1920, 24


class AssemblyError(RuntimeError):
    """Fehler beim Mastering mit klarer Ursache."""


# --------------------------------------------------------------------------- #
# FFmpeg-Helfer
# --------------------------------------------------------------------------- #
def ffmpeg_binary() -> str:
    binary = shutil.which("ffmpeg")
    if binary:
        return binary
    try:
        module = importlib.import_module("imageio_ffmpeg")
        return module.get_ffmpeg_exe()
    except ImportError as exc:  # pragma: no cover
        raise AssemblyError("FFmpeg fehlt: apt-get install ffmpeg oder pip install imageio-ffmpeg") from exc


def run(command: Sequence[str], timeout: int = 3600) -> None:
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=timeout)
    if result.returncode:
        raise AssemblyError("FFmpeg ist fehlgeschlagen:\n" + result.stderr[-4000:])


def _escape_filter_path(path: Path) -> str:
    """Pfad fuer 'ass=filename=...' maskieren (Doppelpunkte, Backslashes, Quotes)."""
    text = str(Path(path).resolve())
    text = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return text


# --------------------------------------------------------------------------- #
# Manifest-Pruefung
# --------------------------------------------------------------------------- #
@dataclass
class ShotClip:
    shot_id: int
    path: Path
    start_frame: int
    frames: int

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.frames


def load_manifest(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise AssemblyError(f"Render-Manifest fehlt: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("shots"), list) or not data["shots"]:
        raise AssemblyError("Manifest enthaelt keine Shots")
    return data


def collect_clips(manifest: dict, timeline: dict, shots_dir: Optional[Path] = None) -> list[ShotClip]:
    """Prueft, dass die Shots die Timeline lueckenlos und frame-exakt abdecken."""
    fps = int(timeline.get("fps", FPS))
    if fps != FPS:
        raise AssemblyError(f"Timeline hat {fps} fps, erwartet {FPS}")
    if int(timeline.get("width", WIDTH)) != WIDTH or int(timeline.get("height", HEIGHT)) != HEIGHT:
        raise AssemblyError("Timeline ist nicht 1080x1920 (9:16)")
    clips: list[ShotClip] = []
    for entry in manifest["shots"]:
        shot_id = int(entry["id"])
        path = Path(entry["path"])
        if not path.is_file() and shots_dir is not None:
            candidate = Path(shots_dir) / path.name
            if candidate.is_file():
                path = candidate
        if not path.is_file():
            raise AssemblyError(f"Gerenderter Shot fehlt: {path}")
        frames = int(entry.get("frames") or 0)
        if frames <= 0:
            raise AssemblyError(f"Shot {shot_id} hat keine Framezahl im Manifest")
        clips.append(ShotClip(shot_id, path, int(entry.get("start_frame", 0)), frames))
    clips.sort(key=lambda c: c.start_frame)
    expected = 0
    for clip in clips:
        if clip.start_frame != expected:
            raise AssemblyError(
                f"Shots sind nicht lueckenlos: Shot {clip.shot_id} beginnt bei "
                f"Frame {clip.start_frame}, erwartet {expected}")
        expected = clip.end_frame
    total = int(timeline["total_frames"])
    if expected != total:
        raise AssemblyError(f"Shots decken {expected} Frames ab, die Timeline hat {total}. "
                            "Bitte fehlende Shots rendern.")
    return clips


# --------------------------------------------------------------------------- #
# Filtergraph (pur, testbar)
# --------------------------------------------------------------------------- #
def build_ffmpeg_command(clips: list[ShotClip], audio: Path, output: Path,
                         subtitles: Optional[Path] = None,
                         width: int = WIDTH, height: int = HEIGHT, fps: int = FPS,
                         total_frames: Optional[int] = None,
                         crf: int = 18, preset: str = "medium",
                         fonts_dir: Optional[Path] = None,
                         audio_bitrate: str = "192k") -> list[str]:
    """Baut die FFmpeg-Argumente (ohne Binary und ohne Ausfuehrung)."""
    if not clips:
        raise AssemblyError("Keine Shots zum Zusammensetzen")
    total_frames = total_frames or sum(clip.frames for clip in clips)
    args: list[str] = ["-y", "-hide_banner", "-loglevel", "error"]
    for clip in clips:
        args += ["-i", str(Path(clip.path).resolve())]
    args += ["-i", str(Path(audio).resolve())]
    audio_index = len(clips)

    filters: list[str] = []
    for index, clip in enumerate(clips):
        filters.append(
            f"[{index}:v]fps={fps},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
            f"tpad=stop_mode=clone:stop_duration={clip.frames / fps:.6f},"
            f"trim=end_frame={clip.frames},setpts=PTS-STARTPTS[v{index}]")
    filters.append("".join(f"[v{index}]" for index in range(len(clips))) +
                   f"concat=n={len(clips)}:v=1:a=0[vcat]")
    video_label = "[vcat]"
    if subtitles is not None:
        fonts = f":fontsdir='{_escape_filter_path(Path(fonts_dir))}'" if fonts_dir else ""
        filters.append(f"[vcat]ass=filename='{_escape_filter_path(Path(subtitles))}'{fonts}[vsub]")
        video_label = "[vsub]"
    filters.append(f"{video_label}format=yuv420p[vout]")
    filters.append(f"[{audio_index}:a]aresample=48000,"
                   f"atrim=duration={total_frames / fps:.6f},asetpts=PTS-STARTPTS[aout]")

    args += ["-filter_complex", ";".join(filters),
             "-map", "[vout]", "-map", "[aout]",
             "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
             "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
             "-r", str(fps), "-g", str(fps * 2), "-fps_mode", "cfr",
             "-c:a", "aac", "-b:a", audio_bitrate, "-ar", "48000", "-ac", "2",
             "-t", f"{total_frames / fps:.6f}",
             "-movflags", "+faststart", str(Path(output).resolve())]
    return args


# --------------------------------------------------------------------------- #
# Mastering
# --------------------------------------------------------------------------- #
def assemble(timeline: dict, manifest: dict, audio: Path, output: Path,
             subtitles: bool = False, config: Optional[dict] = None,
             subtitles_path: Optional[Path] = None,
             storyboard: Optional[Path] = None, report: Optional[Path] = None,
             shots_dir: Optional[Path] = None, work_dir: Optional[Path] = None,
             crf: int = 18, preset: str = "medium") -> dict:
    """Schneidet den finalen 9:16-Film und schreibt Storyboard + Bericht."""
    if not isinstance(subtitles, bool):
        raise AssemblyError("'subtitles' muss true oder false sein")
    config = config or {}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(work_dir or output.parent / "work")
    work_dir.mkdir(parents=True, exist_ok=True)
    audio = Path(audio)
    if not audio.is_file():
        raise AssemblyError(f"Master-Audio fehlt: {audio}")

    clips = collect_clips(manifest, timeline, shots_dir)
    total_frames = int(timeline["total_frames"])
    ass_file: Optional[Path] = None
    if subtitles:
        if subtitles_path and Path(subtitles_path).is_file():
            ass_file = Path(subtitles_path)
        else:
            sound_design = importlib.import_module("1_system.audio.sound_design")
            style_cfg = config.get("untertitel_stil") or {}
            safe_cfg = config.get("safe_zone") or {}
            style_choice = str(style_cfg.get("font", "inter"))
            font_name = font_manager.font_family_for_ass(style_choice, allow_download=False)
            raw_hl = str(style_cfg.get("highlight", "#FFD700")).strip().lstrip("#")
            hl_bgr = (f"{raw_hl[4:6]}{raw_hl[2:4]}{raw_hl[0:2]}".upper()
                      if len(raw_hl) == 6 else "00D7FF")
            style = sound_design.SubtitleStyle(
                font=font_name,
                font_size=int(style_cfg.get("size", 62)),
                highlight=hl_bgr,
                margin_v=int(safe_cfg.get("bottom_px", sound_design.SAFE_ZONE_BOTTOM_PX)),
            )
            ass_file = sound_design.build_tiktok_subtitles(
                timeline, work_dir / "captions.ass", style=style,
                width=WIDTH, height=HEIGHT)

    args = build_ffmpeg_command(clips, audio, output, ass_file,
                                total_frames=total_frames, crf=crf, preset=preset,
                                fonts_dir=font_manager.fonts_dir() if ass_file else None)
    run([ffmpeg_binary(), *args])
    if not output.is_file() or output.stat().st_size < 10_000:
        raise AssemblyError("Der finale Film wurde nicht (oder fehlerhaft) geschrieben")

    result = {
        "output": str(output),
        "size_mb": round(output.stat().st_size / 1_048_576, 2),
        "duration": round(total_frames / FPS, 2),
        "frames": total_frames,
        "shots": len(clips),
        "subtitles": bool(subtitles),
        "subtitle_file": str(ass_file) if ass_file else None,
        "title": timeline.get("film_title", "Film"),
    }
    if storyboard:
        result["storyboard"] = str(make_storyboard(output, timeline, clips, Path(storyboard)))
    if report:
        result["report"] = str(write_report(result, timeline, manifest, Path(report),
                                            config))
    return result


# --------------------------------------------------------------------------- #
# Storyboard + Bericht
# --------------------------------------------------------------------------- #
def _label_font(size: int = 22):
    try:
        from PIL import ImageFont
    except ImportError:  # pragma: no cover
        return None
    for style in ("inter", "roboto"):
        path = font_manager.resolve(style, allow_download=False)
        if path:
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_storyboard(video: Path, timeline: dict, clips: list[ShotClip],
                    output: Path, thumb=(270, 480), columns: Optional[int] = None) -> Path:
    """Erzeugt ein Uebersichtsbild: pro Shot ein Frame, mit Nummer und Zeit."""
    from PIL import Image, ImageDraw, ImageOps

    ffmpeg = ffmpeg_binary()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []
    labels: list[str] = []
    with __import__("tempfile").TemporaryDirectory(prefix="storyboard_") as tmp:
        for index, clip in enumerate(clips):
            mid = (clip.start_frame + clip.frames / 2) / FPS
            frame_path = Path(tmp) / f"f{index}.png"
            run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-ss", f"{mid:.3f}", "-i", str(video), "-frames:v", "1", str(frame_path)])
            if not frame_path.is_file():
                continue
            image = Image.open(frame_path).convert("RGB")
            frames.append(ImageOps.fit(image, thumb, method=Image.LANCZOS))
            label = f"#{clip.shot_id}  {clip.start_frame / FPS:.1f}s"
            labels.append(label)
    if not frames:
        raise AssemblyError("Storyboard konnte keine Frames aus dem Film extrahieren")
    columns = columns or min(5, len(frames))
    rows = math.ceil(len(frames) / columns)
    padding, header = 8, 34
    board = Image.new("RGB", (columns * (thumb[0] + padding) + padding,
                              rows * (thumb[1] + padding + header) + padding), "#111214")
    draw = ImageDraw.Draw(board)
    font = _label_font(20)
    for index, image in enumerate(frames):
        x = padding + (index % columns) * (thumb[0] + padding)
        y = padding + (index // columns) * (thumb[1] + padding + header)
        board.paste(image, (x, y + header))
        draw.text((x + 4, y + 6), labels[index], fill="#F2F3F3", font=font)
    board.save(output, optimize=True)
    return output


def write_report(result: dict, timeline: dict, manifest: dict, path: Path,
                 config: Optional[dict] = None) -> Path:
    config = config or {}
    stats_lines = [
        f"# Render-Bericht: {result.get('title', 'Film')}",
        "",
        "## Ergebnis",
        "",
        f"* Datei: `{Path(result['output']).name}` ({result['size_mb']} MB)",
        f"* Format: **9:16, 1080x1920, 24 fps**, {result['duration']} s "
        f"({result['frames']} Frames)",
        f"* Shots: {result['shots']}",
        f"* Untertitel: **{'eingebrannt' if result['subtitles'] else 'aus'}**",
        f"* Musik: {(config.get('musik') or {}).get('mood', 'melancholisch')}",
        "",
        "## Shots",
        "",
        "| Shot | Segment | Start | Frames | Dauer | Licht |",
        "|---|---|---|---|---|---|",
    ]
    by_id = {int(entry["id"]): entry for entry in manifest.get("shots", [])}
    for shot in timeline.get("shots", []):
        entry = by_id.get(int(shot["id"]), {})
        stats_lines.append(
            f"| {shot['id']} | {shot['segment_id']} | {shot['start_seconds']:.2f} s | "
            f"{shot['frames']} | {shot['frames'] / FPS:.2f} s | "
            f"{entry.get('lighting', '-')} |")
    stats_lines += ["", "## Kamera", "", "| Shot | Bewegung | Brennweite | Weg (Studs) |", "|---|---|---|---|"]
    for shot in timeline.get("shots", []):
        entry = by_id.get(int(shot["id"]), {})
        camera = entry.get("camera") or {}
        stats_lines.append(f"| {shot['id']} | {camera.get('move', '-')} | "
                           f"{camera.get('focal_mm', '-')} mm | {camera.get('travel_studs', '-')} |")
    stats_lines += ["", "_Automatisch erzeugt von 1_system/tools/assemble_final.py_", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(stats_lines), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def read_config(path: Optional[Path]) -> dict:
    if path and Path(path).is_file():
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Finalen 9:16-Film schneiden")
    parser.add_argument("--timeline", type=Path, default=Path("render_session/timeline_resolved.json"))
    parser.add_argument("--manifest", type=Path, default=Path("render_output/shots/render_manifest.json"))
    parser.add_argument("--audio", type=Path, default=Path("render_session/master_audio.wav"))
    parser.add_argument("--config", type=Path, default=Path("2_aktueller_film/film_config.yaml"))
    parser.add_argument("--output", type=Path, default=Path("render_output/final_film.mp4"))
    parser.add_argument("--storyboard", type=Path, default=Path("render_output/storyboard.png"))
    parser.add_argument("--report", type=Path, default=Path("render_output/film_info.md"))
    parser.add_argument("--subtitles", choices=("auto", "true", "false"), default="auto",
                        help="auto = Wert aus film_config.yaml")
    parser.add_argument("--subtitles-file", type=Path, default=None)
    parser.add_argument("--shots-dir", type=Path, default=None)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="medium")
    args = parser.parse_args(argv)

    config = read_config(args.config)
    timeline = json.loads(args.timeline.read_text(encoding="utf-8"))
    manifest = load_manifest(args.manifest)
    if args.subtitles == "auto":
        value = config.get("subtitles")
        if not isinstance(value, bool):
            raise SystemExit("film_config.yaml: 'subtitles' muss true oder false sein")
        subtitles = value
    else:
        subtitles = args.subtitles == "true"

    subtitles_file = args.subtitles_file
    if subtitles_file is None:
        default_captions = args.timeline.parent / "captions.ass"
        if default_captions.is_file():
            subtitles_file = default_captions

    result = assemble(timeline, manifest, args.audio, args.output, subtitles=subtitles,
                      config=config, subtitles_path=subtitles_file,
                      storyboard=args.storyboard, report=args.report,
                      shots_dir=args.shots_dir, crf=args.crf, preset=args.preset)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    summary_path = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write("## Fertiger Film\n\n")
            stream.write(f"* `{Path(result['output']).name}` - {result['duration']} s, "
                         f"9:16 1080x1920, {result['size_mb']} MB\n")
            stream.write(f"* Untertitel: {'an' if result['subtitles'] else 'aus'}\n")
            stream.write(f"* Shots: {result['shots']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
