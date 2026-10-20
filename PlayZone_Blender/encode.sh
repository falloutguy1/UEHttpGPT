#!/bin/bash
# Combine the rendered PNG sequence and the synthesized soundtrack into the final MP4.
# 960x540 Cycles frames are upscaled to 1280x720 and given a light film grain at encode time.
set -euo pipefail
cd "$(dirname "$0")"
count=$(ls frames/f_*.png | wc -l)
if [ "$count" -ne 1200 ]; then echo "expected 1200 frames, found $count" >&2; exit 1; fi
VF="scale=1280:720:flags=lanczos,noise=alls=5:allf=t,format=yuv420p"
# two-pass at a fixed bitrate: temporal grain makes CRF files balloon (~200 MB at CRF 18)
ffmpeg -y -loglevel error -framerate 24 -i frames/f_%04d.png -vf "$VF" \
  -c:v libx264 -preset slow -tune grain -b:v 6500k -pass 1 -passlogfile /tmp/playzone2pass -an -f null /dev/null
ffmpeg -y -loglevel error -framerate 24 -i frames/f_%04d.png -i soundtrack.wav -vf "$VF" \
  -c:v libx264 -preset slow -tune grain -b:v 6500k -maxrate 9000k -bufsize 13000k -pass 2 \
  -passlogfile /tmp/playzone2pass -c:a aac -b:a 192k -movflags +faststart PLAY_ZONE_horror_50s.mp4
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate \
  -of compact PLAY_ZONE_horror_50s.mp4
