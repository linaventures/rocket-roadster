"""Generate the drive sound effects with ElevenLabs Sound Effects v2 through fal ($0.002 per second).
  python tools/el_sfx.py <out dir>
Each job is submitted once (never resubmitted to poll); failures are reported, not retried."""
import os, sys, json, threading
# fal helper (run_model / download); point FAL_SCRIPTS at your copy. The fal key is read from the environment or Keychain.
sys.path.insert(0, os.environ.get('FAL_SCRIPTS', os.path.expanduser('~/.claude/skills/fal-ai/scripts')))
from fal_run import run, download
OUT = sys.argv[1]
SFX = {
  'gravel':   ('Close-up sound of car tyres rolling steadily over a dry gravel dirt road at medium speed, constant crunching and popping stones, no engine, no music', 8, True),
  'wind':     ('Steady wind rushing past a fast moving car, smooth broadband air whoosh and buffeting, no engine, no music', 8, True),
  'thruster': ('Powerful cold gas thruster firing continuously, high pressure compressed air jet, sustained hissing roar, no music', 6, True),
  'whine':    ('Electric car motor accelerating smoothly, high pitched electric motor and inverter whine like a Tesla, clean futuristic hum, no combustion engine, no music', 6, True),
  'avas':     ('Futuristic electric vehicle pedestrian warning sound at low speed, soft low synthetic hum with a gentle rising tone, no music', 4, True),
  'ignite':   ('Rocket thrusters igniting with a sharp pressurised burst and a quick building roar', 2, False),
  'land':     ('Heavy sports car landing hard on a dirt road after a jump, deep suspension thud, gravel scatter', 1.5, False),
  'crash':    ('Car crashing into rocky ground at speed, heavy metal crunch, scraping and debris', 2.5, False),
}
res = {}
def go(name, text, dur, loop):
    try:
        r = run('fal-ai/elevenlabs/sound-effects/v2', {'text': text, 'duration_seconds': dur, 'loop': loop, 'prompt_influence': 0.5, 'output_format': 'mp3_44100_128'})
        res[name] = {'files': [str(p) for p in download(r, OUT, name)], 'request_id': r.get('request_id')}
    except Exception as e:
        res[name] = {'error': str(e)[:300]}
ts = [threading.Thread(target=go, args=(k, *v)) for k, v in SFX.items()]
[t.start() for t in ts]; [t.join() for t in ts]
print(json.dumps(res, indent=1)); print('billed seconds (if all ran):', sum(v[1] for v in SFX.values()))
