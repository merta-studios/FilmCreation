"""Frame-aligned MP4 assembly for independently rendered shots and speech clips."""
from __future__ import annotations
import argparse
import importlib
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
import yaml


def ffmpeg_binary():
    binary = shutil.which('ffmpeg')
    if binary:
        return binary
    try:
        return importlib.import_module('imageio_ffmpeg').get_ffmpeg_exe()
    except ImportError as e:
        raise RuntimeError('FFmpeg fehlt; installiere ffmpeg oder imageio-ffmpeg') from e


def run(command):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise RuntimeError('FFmpeg fehlgeschlagen: ' + result.stderr[-4000:])


def assemble(timeline, shots, audios, output, subtitles=False, width=1080, height=1920, storyboard=None):
    """Shots correspond 1:1 to ordered timeline segments, including their pauses.

    Segment start frames must begin at zero and increase. Audio is offset to
    segment start; videos are trimmed at exact frame boundaries. No inference of
    missing shots, speech or durations is attempted.
    """
    fps = int(timeline['fps'])
    segments = timeline['segments']
    total_frames = int(timeline['total_frames'])
    if fps != 24 or not segments or len(shots) != len(segments) or len(audios) != len(segments):
        raise ValueError('24 fps und je ein Video/Audio pro Segment erforderlich')
    starts = [int(s['start_frame']) for s in segments] + [total_frames]
    if starts[0] != 0 or any(a >= b for a,b in zip(starts,starts[1:])):
        raise ValueError('Ungültige oder leere Segment-Framebereiche')
    if not all(Path(p).is_file() for p in [*shots, *audios]):
        raise FileNotFoundError('Mindestens ein Shot oder Sprachclip fehlt')
    if not isinstance(subtitles, bool):
        raise ValueError('subtitles muss Boolean sein')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_binary()
    command = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error']
    for path in [*shots, *audios]:
        command += ['-i', str(Path(path).resolve())]
    filters = []
    for i in range(len(segments)):
        frames = starts[i+1] - starts[i]
        filters.append(f'[{i}:v]fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,tpad=stop_mode=clone:stop_duration={frames/fps:.6f},trim=end_frame={frames},setpts=PTS-STARTPTS[v{i}]')
    filters.append(''.join(f'[v{i}]' for i in range(len(segments))) + f'concat=n={len(segments)}:v=1:a=0[v]')
    for i, start in enumerate(starts[:-1]):
        delay = round(start * 1000 / fps)
        filters.append(f'[{len(segments)+i}:a]aresample=48000,atrim=duration={(starts[i+1]-start)/fps:.6f},asetpts=PTS-STARTPTS,adelay={delay}:all=1[a{i}]')
    filters.append(''.join(f'[a{i}]' for i in range(len(segments))) + f'amix=inputs={len(segments)}:duration=longest:normalize=0,apad,atrim=duration={total_frames/fps:.6f},loudnorm=I=-14:TP=-1.5:LRA=11[a]')
    with tempfile.TemporaryDirectory(prefix='film_') as tmp:
        tmp = Path(tmp)
        final_video = '[v]'
        if subtitles:
            path = tmp / 'captions.ass'
            importlib.import_module('1_system.audio.sound_design').build_tiktok_subtitles(timeline, path)
            # Use a controlled temporary path and escape filter metacharacters.
            escaped = str(path).replace('\\','\\\\').replace(':','\\:').replace("'", "\\'")
            filters.append(f"[v]ass='{escaped}'[sub]")
            final_video = '[sub]'
        command += ['-filter_complex', ';'.join(filters), '-map', final_video, '-map', '[a]',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'medium',
                    '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', str(output)]
        run(command)
        if storyboard:
            from PIL import Image, ImageOps, ImageDraw
            images = []
            for i, (shot, start, end) in enumerate(zip(shots, starts, starts[1:])):
                img = tmp / f'{i}.png'
                run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-ss', str((end-start)/fps/2), '-i', str(shot), '-frames:v', '1', str(img)])
                images.append(Image.open(img).convert('RGB'))
            thumb = (270, 480)
            board = Image.new('RGB', (thumb[0]*len(images), thumb[1]), '#151515')
            for i, image in enumerate(images):
                board.paste(ImageOps.fit(image, thumb), (i*thumb[0],0))
            Path(storyboard).parent.mkdir(parents=True, exist_ok=True)
            board.save(storyboard)
    return output


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--timeline', type=Path, required=True)
    p.add_argument('--shots-dir', type=Path, required=True)
    p.add_argument('--audio-dir', type=Path, required=True)
    p.add_argument('--config', type=Path, default=Path('2_aktueller_film/film_config.yaml'))
    p.add_argument('--output', type=Path, default=Path('render_output/final_film.mp4'))
    p.add_argument('--storyboard', type=Path, default=Path('render_output/storyboard.png'))
    args = p.parse_args()
    tl = json.loads(args.timeline.read_text(encoding='utf8'))
    cfg = yaml.safe_load(args.config.read_text(encoding='utf8'))
    shots = [args.shots_dir / f'shot_{s["segment_id"]:03d}.mp4' for s in tl['segments']]
    audio = [args.audio_dir / f'seg_{s["segment_id"]:03d}.mp3' for s in tl['segments']]
    assemble(tl, shots, audio, args.output, subtitles=cfg['subtitles'], storyboard=args.storyboard)

if __name__ == '__main__':
    main()
