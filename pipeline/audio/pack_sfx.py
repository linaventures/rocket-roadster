"""Level and pack the ElevenLabs drive sound effects into one base64 JSON file for the page.
  python tools/pack_sfx.py <dir with raw mp3s> <out sfx.part0.txt>
Loops get their slow level swings flattened (they repeat every few seconds, so a swell would pulse) and sit at
-20 dBFS RMS; one-shots are peak-normalised. Everything is mono MP3 at 96 kbps (positional audio isn't used)."""
import base64, json, os, subprocess, sys, tempfile, wave
import numpy as np
SRC, OUT = sys.argv[1], sys.argv[2]
LOOPS = ['gravel', 'wind', 'thruster', 'whine', 'avas']
ONESHOTS = ['ignite', 'land', 'crash']
pack = {}
with tempfile.TemporaryDirectory() as tmp:
    for name in LOOPS + ONESHOTS:
        wav = os.path.join(tmp, name + '.wav')
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', os.path.join(SRC, name + '.mp3'), '-ac', '1', '-ar', '44100', wav], check=True)
        w = wave.open(wav); sr = w.getframerate(); x = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(float) / 32768
        if name in LOOPS:
            win = int(sr * 0.05); e = np.sqrt(np.convolve(x * x, np.ones(win) / win, 'same'))
            k = int(sr * 0.4); e = np.convolve(np.pad(e, k, mode='wrap'), np.ones(k) / k, 'same')[k:-k]   # wrap: the loop's ends see each other
            x = x / np.maximum(e, e.mean() * 0.25) * e.mean()
            x *= 10 ** (-20 / 20) / np.sqrt((x * x).mean())
        x *= min(1.0, 0.89 / np.abs(x).max()) if name in LOOPS else 0.89 / np.abs(x).max()
        out_wav = os.path.join(tmp, name + '-lv.wav'); ww = wave.open(out_wav, 'wb'); ww.setnchannels(1); ww.setsampwidth(2); ww.setframerate(sr)
        ww.writeframes((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes()); ww.close()
        mp3 = os.path.join(tmp, name + '.mp3')
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', out_wav, '-c:a', 'libmp3lame', '-b:a', '96k', '-write_xing', '1', mp3], check=True)
        pack[name] = base64.b64encode(open(mp3, 'rb').read()).decode()
        print('%-9s %5.2fs rms %5.1f dBFS peak %.2f  %6d bytes' % (name, len(x) / sr, 20 * np.log10(np.sqrt((x * x).mean()) + 1e-9), np.abs(x).max(), os.path.getsize(mp3)))
open(OUT, 'w').write(json.dumps(pack))
print('wrote', OUT, os.path.getsize(OUT), 'bytes')
