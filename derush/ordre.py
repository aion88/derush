"""derush ordre : assemble des prises DÉJÀ montées bout à bout, coupes sèches, dans l'ordre donné.
usage : ordre.py <sortie.mp4> <prise1.mp4> <prise2.mp4> ...   (format et fps de la première)"""
import subprocess, sys, json

def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                        "-of", "json", p], capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)["streams"][0]
    return s["width"], s["height"], s["r_frame_rate"]

def main(out, *clips):
    if not clips:
        sys.exit("aucune prise")
    w, h, fps = probe(clips[0])
    args = ["ffmpeg", "-loglevel", "error", "-y"]
    for c in clips:
        args += ["-i", c]
    parts, lab = [], ""
    for i in range(len(clips)):
        parts.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}]")
        parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
        lab += f"[v{i}][a{i}]"
    parts.append(f"{lab}concat=n={len(clips)}:v=1:a=1[v][a]")
    args += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out]
    subprocess.run(args, check=True)
    print(f"{len(clips)} prises → {out}")

if __name__ == "__main__":
    main(*sys.argv[1:])
