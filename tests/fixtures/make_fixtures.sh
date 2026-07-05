#!/bin/bash
# Generate tiny synthetic media fixtures for shoot-pipeline tests.
# No real footage needed: ffmpeg test sources stand in for clips.
#
# Usage: ./make_fixtures.sh [output_dir]   (default: ./sample_shoot)
set -euo pipefail

OUT="${1:-$(dirname "$0")/sample_shoot}"
mkdir -p "$OUT/cam_a" "$OUT/cam_b" "$OUT/audio" "$OUT/photos"

# "Interview": tone bursts approximate speech-like audio activity
ffmpeg -y -v error -f lavfi -i "testsrc2=size=640x360:rate=30:duration=8" \
  -f lavfi -i "sine=frequency=220:duration=8,volume='if(lt(mod(t,2),1),1,0.02)':eval=frame" \
  -c:v libx264 -preset ultrafast -c:a aac -shortest "$OUT/cam_a/interview.mp4"

# "Action": fast-moving pattern, loud constant audio (engine-ish)
ffmpeg -y -v error -f lavfi -i "testsrc2=size=640x360:rate=60:duration=6" \
  -f lavfi -i "anoisesrc=color=brown:duration=6:amplitude=0.7" \
  -c:v libx264 -preset ultrafast -c:a aac -shortest "$OUT/cam_b/action.mp4"

# Silent B-roll: slow pattern, near-silence
ffmpeg -y -v error -f lavfi -i "smptebars=size=640x360:rate=24:duration=6" \
  -f lavfi -i "anullsrc=r=48000:cl=stereo:duration=6" \
  -c:v libx264 -preset ultrafast -c:a aac -shortest "$OUT/cam_b/broll_silent.mp4"

# Standalone audio recording
ffmpeg -y -v error -f lavfi -i "sine=frequency=440:duration=4" \
  -c:a pcm_s16le "$OUT/audio/lav_mic.wav"

# Photos: sharp frames + one blurred near-duplicate (burst simulation)
ffmpeg -y -v error -f lavfi -i "testsrc2=size=1280x720" -frames:v 1 "$OUT/photos/IMG_0001.jpg"
ffmpeg -y -v error -f lavfi -i "testsrc2=size=1280x720" -frames:v 1 -vf "boxblur=10" "$OUT/photos/IMG_0002.jpg"
ffmpeg -y -v error -f lavfi -i "smptebars=size=1280x720" -frames:v 1 "$OUT/photos/IMG_0003.jpg"

echo "Fixtures written to $OUT"
