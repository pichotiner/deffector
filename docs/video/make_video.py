"""Монтаж видео из записей по списку вырезок — одной командой, через ffmpeg.

    python docs/video/make_video.py docs/video/scenario.json
    python docs/video/make_video.py docs/video/proof.json

Список вырезок — JSON (пример — scenario.json):

    {"output": "../../demo/video/scenario.mp4",
     "title": {"text": "Deffector", "sub": "AR-помощник инженера", "seconds": 3},
     "clips": [{"phone": "phone.mp4", "from": "0:05", "to": "0:12", "caption": "1. Запуск — сразу камера"},
               {"phone": "phone.mp4", "side": "side.mp4", "side_shift": 1.5,
                "from": "1:10", "to": "1:40", "speed": 2, "caption": "6. ИИ-анализ"}],
     "final": {"text": "Все 10 шагов ТЗ", "sub": "работает без интернета", "seconds": 3}}

- phone — запись экрана телефона; side — съёмка со стороны (необязательно): тогда экран
  делится, телефон слева. side_shift — на сколько секунд съёмка со стороны началась раньше
  записи экрана (отрицательное — позже).
- from / to — время в записи экрана: секунды или «м:сс»; speed — ускорение (2 = вдвое быстрее).
- Пути к записям — относительно файла со списком. Итог — MP4, H.264, 1920×1080, 30 кадров/с,
  без звука. Нужен ffmpeg в PATH; шрифт берётся системный (Arial в Windows).
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

W, H, FPS = 1920, 1080, 30
BG = "0x0f1720"
FONTS = [  # жирный шрифт с кириллицей
    "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
ENCODE = ["-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
          "-r", str(FPS), "-video_track_timescale", "15360"]


def fail(text):
    sys.exit(f"[XX] {text}")


def seconds(value):
    """«1:05.5», «65.5» или число → секунды."""
    if isinstance(value, (int, float)):
        return float(value)
    total = 0.0
    for part in str(value).split(":"):
        total = total * 60 + float(part.replace(",", "."))
    return total


def run(args, cwd):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                       cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        fail("ffmpeg: " + r.stderr.strip()[-1500:])


def text_file(tmp, name, text):
    # Текст — через файл: кириллица, двоеточия и кавычки не требуют экранирования
    (tmp / name).write_text(text, encoding="utf-8")
    return name


def card(tmp, index, spec):
    """Заставка или финальный кадр: две строки текста на тёмном фоне."""
    out = f"part{index:02d}.mp4"
    draw = (f"drawtext=expansion=none:fontfile=font.ttf:textfile={text_file(tmp, f't{index}.txt', spec['text'])}:"
            f"fontsize=84:fontcolor=white:x=(w-text_w)/2:y=420")
    if spec.get("sub"):
        draw += (f",drawtext=expansion=none:fontfile=font.ttf:textfile={text_file(tmp, f's{index}.txt', spec['sub'])}:"
                 f"fontsize=44:fontcolor=0x9fb3c8:x=(w-text_w)/2:y=560")
    run(["-f", "lavfi", "-i", f"color=c={BG}:s={W}x{H}:r={FPS}:d={float(spec.get('seconds', 3))}",
         "-vf", draw, *ENCODE, out], tmp)
    return out


def clip(tmp, index, spec, base):
    out = f"part{index:02d}.mp4"
    start, end = seconds(spec["from"]), seconds(spec["to"])
    if end <= start:
        fail(f"вырезка {index}: «to» должно быть больше «from»")
    speed = float(spec.get("speed", 1))
    phone = (base / spec["phone"]).resolve()
    if not phone.exists():
        fail(f"вырезка {index}: нет файла {phone}")
    inputs = ["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(phone)]
    chain = [f"color=c={BG}:s={W}x{H}:r={FPS}[bg]",
             f"[0:v]setpts=PTS/{speed},fps={FPS},scale=-2:940[p]"]
    if spec.get("side"):
        side = (base / spec["side"]).resolve()
        if not side.exists():
            fail(f"вырезка {index}: нет файла {side}")
        shift = float(spec.get("side_shift", 0))
        if start + shift < 0:
            fail(f"вырезка {index}: съёмка со стороны начинается позже этого места — уберите «side»")
        inputs += ["-ss", f"{start + shift:.3f}", "-to", f"{end + shift:.3f}", "-i", str(side)]
        chain += [f"[1:v]setpts=PTS/{speed},fps={FPS},"
                  "scale=w=1180:h=900:force_original_aspect_ratio=decrease[s]",
                  "[bg][p]overlay=x=90:y=20:shortest=1[a]",
                  "[a][s]overlay=x=660+(1180-w)/2:y=20+(940-h)/2[v0]"]
    else:
        chain += ["[bg][p]overlay=x=(W-w)/2:y=20:shortest=1[v0]"]
    last = "[v0]"
    if spec.get("caption"):
        cap = text_file(tmp, f"c{index}.txt", spec["caption"])
        chain += [f"[v0]drawbox=x=0:y=975:w={W}:h=105:color=black@0.8:t=fill,"
                  f"drawtext=expansion=none:fontfile=font.ttf:textfile={cap}:fontsize=46:fontcolor=white:"
                  f"x=(w-text_w)/2:y=1003[v1]"]
        last = "[v1]"
    run([*inputs, "-filter_complex", ";".join(chain), "-map", last, *ENCODE, out], tmp)
    return out


def main():
    if len(sys.argv) != 2:
        fail("укажите список вырезок: python docs/video/make_video.py docs/video/scenario.json")
    if not shutil.which("ffmpeg"):
        fail("нет ffmpeg в PATH. Windows: winget install Gyan.FFmpeg, затем открыть новое окно")
    plan_path = Path(sys.argv[1]).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    base = plan_path.parent
    font = next((Path(f) for f in FONTS if Path(f).exists()), None)
    if font is None:
        fail("не найден шрифт с кириллицей — допишите путь в FONTS")
    output = (base / plan["output"]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        shutil.copy(font, tmp / "font.ttf")  # рядом с ffmpeg: путь без двоеточий и пробелов
        parts, index = [], 0
        if plan.get("title"):
            parts.append(card(tmp, index, plan["title"]))
        for spec in plan["clips"]:
            index += 1
            print(f"[..] вырезка {index} из {len(plan['clips'])}: {spec.get('caption', '')}", flush=True)
            parts.append(clip(tmp, index, spec, base))
        if plan.get("final"):
            parts.append(card(tmp, index + 1, plan["final"]))
        (tmp / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        run(["-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "-movflags", "+faststart",
             str(output)], tmp)
    print(f"[OK] {output} — {output.stat().st_size / 1e6:.1f} МБ")
    if output.stat().st_size > 50e6:
        print("[!!] больше 50 МБ: в репозиторий не класть, загрузить на диск и дать ссылку в README.md")


if __name__ == "__main__":
    main()
