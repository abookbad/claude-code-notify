import wave, math, struct, os, sys
SR = 44100

def render(samples, path):
    peak = max(abs(s) for s in samples) or 1.0
    samples = [s / peak * 0.85 for s in samples]
    # de-click edges
    n = int(SR * 0.004)
    for i in range(min(n, len(samples))):
        samples[i] *= i / n
        samples[-1 - i] *= i / n
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples))
    return path

def bell(buf, start, freq, dur, amp=1.0, partials=((1,1.0,1.0),(2,0.42,0.6),(3,0.18,0.45),(4.2,0.09,0.35))):
    """Struck-bell tone: harmonic partials, each decaying at its own rate."""
    i0 = int(start * SR)
    for i in range(int(dur * SR)):
        t = i / SR
        v = 0.0
        for mult, a, decay in partials:
            v += a * math.sin(2 * math.pi * freq * mult * t) * math.exp(-t / (dur * decay * 0.55))
        atk = min(1.0, t / 0.006)          # soft strike
        idx = i0 + i
        if idx < len(buf):
            buf[idx] += v * amp * atk

def glide(buf, start, f0, f1, dur, amp=1.0):
    """Rising tone with a voice-like timbre - reads as a question."""
    i0 = int(start * SR); ph = 0.0
    for i in range(int(dur * SR)):
        t = i / SR; frac = t / dur
        f = f0 + (f1 - f0) * (frac ** 0.7)
        ph += 2 * math.pi * f / SR
        v = (math.sin(ph) + 0.5 * math.sin(2 * ph) + 0.22 * math.sin(3 * ph) + 0.1 * math.sin(4 * ph))
        env = math.sin(math.pi * min(1.0, frac * 1.05)) ** 0.8
        idx = i0 + i
        if idx < len(buf):
            buf[idx] += v * amp * env

# Output folder: first argument, else ~/.claude/sounds (what the hook plays).
out = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/.claude/sounds")
os.makedirs(out, exist_ok=True)

# DONE: ascending major arpeggio, bell timbre. A5 - C#6 - E6, last note rings out.
buf = [0.0] * int(SR * 1.7)
bell(buf, 0.00, 880.00, 0.55, 0.75)
bell(buf, 0.11, 1108.73, 0.60, 0.80)
bell(buf, 0.22, 1318.51, 1.35, 1.00)
bell(buf, 0.22, 2637.02, 0.70, 0.18)   # shimmer octave
render(buf, os.path.join(out, "done.wav"))

# NEEDS INPUT: two-syllable rising "huh?" - short, low, then up a fifth.
buf = [0.0] * int(SR * 0.62)
glide(buf, 0.00, 300, 330, 0.13, 0.55)
glide(buf, 0.17, 330, 560, 0.34, 1.00)
render(buf, os.path.join(out, "needs-input.wav"))
# AGENTS RUNNING (workflow.wav): two quick soft bells a fourth apart - "on it".
buf = [0.0] * int(SR * 0.75)
bell(buf, 0.00, 1046.50, 0.35, 0.70)   # C6
bell(buf, 0.09, 1396.91, 0.55, 0.85)   # F6
render(buf, os.path.join(out, "workflow.wav"))
print("wrote done.wav, workflow.wav, needs-input.wav to", out)
