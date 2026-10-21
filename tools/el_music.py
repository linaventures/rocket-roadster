import os, sys, json, threading
# fal helper (run_model / download); point FAL_SCRIPTS at your copy. The fal key is read from the environment or Keychain.
sys.path.insert(0, os.environ.get('FAL_SCRIPTS', os.path.expanduser('~/.claude/skills/fal-ai/scripts')))
from fal_run import run, download
OUT = sys.argv[1]
BASE = ("Instrumental melodic organic house with a western desert soul, 118 BPM, A minor. Twangy spaghetti-western electric guitar "
        "with tremolo, spring reverb and slow bends playing a lazy, memorable lead; warm Rhodes electric piano chords; deep rolling "
        "bassline; soft four-on-the-floor kick, shakers, hand claps and wooden hand percussion like distant hoofbeats; a whistled "
        "melody answering the guitar; dusty, sun-baked, laid-back sunset cowboy mood, wide and cinematic, driving through the "
        "Arizona desert. Smooth steady groove from start to end, no vocals, no lyrics.")
TAKES = {
  'take1': BASE + " Warm and mellow, gentle build, guitar-led.",
  'take2': BASE + " A touch more groove and energy, whistle hook up front, deep house bass.",
}
res = {}
def go(name, prompt):
    try:
        r = run('fal-ai/elevenlabs/music', {'prompt': prompt, 'music_length_ms': 120000, 'force_instrumental': True, 'output_format': 'mp3_44100_128'})
        res[name] = {'files': [str(p) for p in download(r, OUT, name)], 'request_id': r.get('request_id')}
    except Exception as e:
        res[name] = {'error': str(e)[:500]}
ts = [threading.Thread(target=go, args=kv) for kv in TAKES.items()]
[t.start() for t in ts]; [t.join() for t in ts]
print(json.dumps(res, indent=1))
