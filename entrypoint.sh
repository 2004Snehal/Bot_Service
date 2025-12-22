#!/bin/bash
set -e

# ----------------------------------------------------------------
# 1. Start Xvfb (Virtual Monitor)
# ----------------------------------------------------------------
# This allows Chrome to launch in "headless" environments.
# Match the resolution used in bot.py (1920x1080)
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# ----------------------------------------------------------------
# 2. Start PulseAudio
# ----------------------------------------------------------------
# NOTE: If you are running this container as ROOT, standard PulseAudio 
# might refuse to start. If it fails, use: 
# pulseaudio -D --system --disallow-exit --disallow-module-loading=0
pulseaudio --start --exit-idle-time=-1 || pulseaudio -D --system --disallow-exit --disallow-module-loading=0

# ----------------------------------------------------------------
# 3. Create Audio Plumbing (The Two Cables)
# ----------------------------------------------------------------

# Sink A: "MeetOutput" (The Ear)
# Chrome speakers -> MeetOutput -> FFmpeg records this
pactl load-module module-null-sink sink_name=MeetOutput sink_properties=device.description="MeetOutput"

# Sink B: "BotMic" (The Mouth)
# Python plays to BotMic -> VirtualMic -> Chrome Microphone
pactl load-module module-null-sink sink_name=BotMic sink_properties=device.description="BotMic"

# Source: "VirtualMic"
# Remap the monitor of Sink B to be a microphone source
pactl load-module module-virtual-source source_name=VirtualMic master=BotMic.monitor source_properties=device.description="Virtual_Microphone"

# Set VirtualMic as the default source (Microphone)
pactl set-default-source VirtualMic

# ----------------------------------------------------------------
# 4. Wait for Audio System (CRITICAL FIX)
# ----------------------------------------------------------------
echo "Waiting for audio devices to initialize..."
TIMEOUT=10
count=0

# We check for BOTH Sinks AND the Virtual Source to prevent race conditions
until pactl list sinks short | grep -q "MeetOutput" && \
      pactl list sinks short | grep -q "BotMic" && \
      pactl list sources short | grep -q "VirtualMic"; do
  
  if [ $count -ge $TIMEOUT ]; then
    echo "ERROR: Timeout waiting for audio devices."
    echo "--- Debug: Sinks Found ---"
    pactl list sinks short
    echo "--- Debug: Sources Found ---"
    pactl list sources short
    exit 1
  fi
  sleep 1
  count=$((count+1))
done
echo "✅ Audio Sinks and VirtualMic confirmed."

# ----------------------------------------------------------------
# 5. Unmute and Set Volume
# ----------------------------------------------------------------
# PulseAudio devices often start muted or at 0 volume in containers.
pactl set-sink-mute MeetOutput 0
pactl set-sink-volume MeetOutput 100%

# ### CRITICAL FIX START ###
# You must explicitly unmute the MONITOR source, or FFmpeg records silence.
pactl set-source-mute MeetOutput.monitor 0
pactl set-source-volume MeetOutput.monitor 100%
# ### CRITICAL FIX END ###

pactl set-sink-mute BotMic 0
pactl set-sink-volume BotMic 100%

pactl set-source-mute VirtualMic 0
pactl set-source-volume VirtualMic 100%

# ----------------------------------------------------------------
# 6. Set System Defaults
# ----------------------------------------------------------------
# This forces Chrome to use our custom pipes since it can't choose them itself.
pactl set-default-sink MeetOutput
pactl set-default-source VirtualMic

# ----------------------------------------------------------------
# 7. Audio System Self-Test
# ----------------------------------------------------------------
echo "🔊 Running Audio System Self-Test..."

# Generate a test tone and record it to verify the audio pipeline works
echo "  -> Generating test tone..."
ffmpeg -f lavfi -i "sine=frequency=440:duration=2" -ar 48000 -ac 1 /tmp/test_tone.wav -y 2>/dev/null

echo "  -> Playing test tone to MeetOutput sink..."
paplay --device=MeetOutput /tmp/test_tone.wav &
PLAY_PID=$!

echo "  -> Recording from MeetOutput.monitor for 3 seconds..."
ffmpeg -f pulse -i MeetOutput.monitor -t 3 -ar 16000 -ac 1 /app/out/audio_selftest.wav -y 2>/dev/null &
REC_PID=$!

# Wait for playback and recording to finish
wait $PLAY_PID 2>/dev/null || true
wait $REC_PID 2>/dev/null || true

# Check if audio was recorded
if [ -f /app/out/audio_selftest.wav ]; then
    SIZE=$(stat -c%s /app/out/audio_selftest.wav 2>/dev/null || echo 0)
    if [ "$SIZE" -gt 1000 ]; then
        echo "✅ Audio Self-Test PASSED: Recorded ${SIZE} bytes"
    else
        echo "❌ Audio Self-Test FAILED: File too small (${SIZE} bytes). Audio routing broken."
    fi
else
    echo "❌ Audio Self-Test FAILED: No file created. FFmpeg or PulseAudio issue."
fi

echo ""
echo "--- Final PulseAudio State ---"
pactl list sinks short
pactl list sources short
echo "------------------------------"
echo ""

# ----------------------------------------------------------------
# 8. Launch the Bot
# ----------------------------------------------------------------
echo "🚀 Starting Application..."

# Check arguments to determine launch mode
if [[ "$1" == http* ]]; then
    # If arg is a URL, pass it to app
    exec python -u app.py "$@"
elif [ -z "$1" ]; then
    # Default launch
    exec python -u app.py
else
    # Run arbitrary command (useful for debugging)
    exec "$@"
fi