/* ---------- Desert soundtrack ---------- */
// An original "desert house" loop synthesised live with Web Audio (no audio files): a four-on-the-floor groove
// under a twangy tremolo guitar, Rhodes-like keys, a warm pad and a whistled tune over the spaghetti-western
// walk Am–G–F–E, with clip-clop hooves. 118 bpm, 32 bars (about 65 s), then it loops. makeSong() takes any
// AudioContext, so the same code renders offline for previews.
const SONG = { bpm: 118, bars: 32 };
function makeSong(ctx, out) {
  const SPB = 60 / SONG.bpm, S16 = SPB / 4, sr = ctx.sampleRate;
  const N = m => 440 * Math.pow(2, (m - 69) / 12);
  const node = (type, props = {}) => { const n = ctx[type](); Object.entries(props).forEach(([k, v]) => (n[k] instanceof AudioParam ? (n[k].value = v) : (n[k] = v))); return n; };
  const pan = (from, to, x) => { const p = ctx.createStereoPanner ? node('createStereoPanner', { pan: x }) : node('createGain'); from.connect(p); p.connect(to); return p; };
  const send = (from, to, amount) => { const g = node('createGain', { gain: amount }); from.connect(g); g.connect(to); return g; };
  const noise = (() => { const b = ctx.createBuffer(1, sr, sr), d = b.getChannelData(0); for (let i = 0; i < sr; i++) d[i] = Math.random() * 2 - 1; return b; })();
  // Buses: everything except the drums pumps under the kick (the house "duck").
  const master = node('createGain', { gain: 0 }), tone = node('createBiquadFilter', { type: 'lowpass', frequency: 18000, Q: 0.5 });
  const comp = node('createDynamicsCompressor', { threshold: -16, ratio: 3, attack: 0.01, release: 0.2 });
  const mix = node('createGain', { gain: 1 }); mix.connect(comp); comp.connect(tone); tone.connect(master); master.connect(out);
  const duck = node('createGain', { gain: 1 }); duck.connect(mix);
  const drums = node('createGain', { gain: 0.9 }); drums.connect(mix);
  // A dark 2.8 s hall for the desert, and a dotted-eighth echo for the guitar and whistle.
  const verb = ctx.createConvolver();
  { const len = Math.floor(sr * 2.8), ir = ctx.createBuffer(2, len, sr);
    for (let c = 0; c < 2; c++) { const d = ir.getChannelData(c); let lp = 0; for (let i = 0; i < len; i++) { lp += 0.35 * ((Math.random() * 2 - 1) - lp); d[i] = lp * Math.pow(1 - i / len, 2.4); } }
    verb.buffer = ir; }
  const verbIn = node('createGain', { gain: 1 }); verbIn.connect(verb); send(verb, duck, 0.5);
  const dly = node('createDelay', { delayTime: SPB * 0.75 }), fb = node('createGain', { gain: 0.32 }), dlp = node('createBiquadFilter', { type: 'lowpass', frequency: 2600 });
  const dlyIn = node('createGain', { gain: 1 }); dlyIn.connect(dly); dly.connect(dlp); dlp.connect(fb); fb.connect(dly); pan(dlp, duck, 0.55);   // echoes answer from the right
  // Guitar: highpass, a presence bump for the twang, and a tremolo (the spaghetti-western shimmer).
  const gtr = node('createGain', { gain: 1.0 }), trem = node('createOscillator', { frequency: 5.6 }), tremD = node('createGain', { gain: 0.22 });
  trem.connect(tremD); tremD.connect(gtr.gain); trem.start();
  const gHP = node('createBiquadFilter', { type: 'highpass', frequency: 140 }), gPk = node('createBiquadFilter', { type: 'peaking', frequency: 2800, gain: 5, Q: 1 });
  gHP.connect(gPk); gPk.connect(gtr); gtr.connect(duck); send(gtr, dlyIn, 0.34); send(gtr, verbIn, 0.45);
  const keysBus = node('createBiquadFilter', { type: 'lowpass', frequency: 2400 }); keysBus.connect(duck); send(keysBus, verbIn, 0.3);
  const padBus = node('createBiquadFilter', { type: 'lowpass', frequency: 900, Q: 0.7 }); padBus.connect(duck); send(padBus, verbIn, 0.6);
  const whistleBus = node('createGain', { gain: 1 }); whistleBus.connect(duck); send(whistleBus, verbIn, 0.55); send(whistleBus, dlyIn, 0.22);
  // Plucked strings (Karplus–Strong), rendered once per pitch.
  const plucks = new Map();
  function pluck(m) {
    if (plucks.has(m)) return plucks.get(m);
    const P = Math.max(2, Math.round(sr / N(m))), len = Math.floor(sr * 2.4), b = ctx.createBuffer(1, len, sr), d = b.getChannelData(0);
    for (let i = 0; i < P; i++) d[i] = Math.random() * 2 - 1;
    for (let i = 1; i < P; i++) d[i] = 0.5 * d[i] + 0.5 * d[i - 1];
    let peak = 0;
    for (let i = P; i < len; i++) { d[i] = 0.996 * (0.56 * d[i - P] + 0.44 * d[i - P - 1 < 0 ? 0 : i - P - 1]); }
    for (let i = 0; i < len; i++) peak = Math.max(peak, Math.abs(d[i]));
    for (let i = 0; i < len; i++) d[i] *= 0.7 / peak;
    plucks.set(m, b); return b;
  }
  const env = (g, t, a, peak, d, sus, end, r) => { g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(peak, t + a); g.gain.setTargetAtTime(sus, t + a, d); g.gain.setTargetAtTime(0, end, r); };
  function kick(t) {
    const o = node('createOscillator'), g = node('createGain');
    o.frequency.setValueAtTime(150, t); o.frequency.exponentialRampToValueAtTime(46, t + 0.09);
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.8, t + 0.004); g.gain.exponentialRampToValueAtTime(0.001, t + 0.38);
    o.connect(g); g.connect(drums); o.start(t); o.stop(t + 0.4);
    duck.gain.setValueAtTime(0.6, t); duck.gain.linearRampToValueAtTime(1, t + 0.22);
  }
  function hit(t, filt, freq, q, peak, decay, toVerb = 0, px = 0) {
    const s = node('createBufferSource', { buffer: noise }), f = node('createBiquadFilter', { type: filt, frequency: freq, Q: q }), g = node('createGain');
    g.gain.setValueAtTime(peak, t); g.gain.exponentialRampToValueAtTime(0.0008, t + decay);
    s.connect(f); f.connect(g); if (px) pan(g, drums, px); else g.connect(drums); if (toVerb) send(g, verbIn, toVerb);
    s.start(t, Math.random() * 0.5); s.stop(t + decay + 0.02);
  }
  function clap(t) { [0, 0.011, 0.023].forEach((o, i) => hit(t + o, 'bandpass', 1400, 0.9, i === 2 ? 0.32 : 0.22, i === 2 ? 0.2 : 0.03, i === 2 ? 0.3 : 0)); }
  function block(t, f, v, px) {
    const o = node('createOscillator', { type: 'triangle', frequency: f }), g = node('createGain');
    g.gain.setValueAtTime(v, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.07);
    o.connect(g); pan(g, drums, px); send(g, verbIn, 0.25); o.start(t); o.stop(t + 0.08);
  }
  function bass(t, m, dur) {
    const o = node('createOscillator', { type: 'sawtooth', frequency: N(m) }), sub = node('createOscillator', { frequency: N(m) }), f = node('createBiquadFilter', { type: 'lowpass', Q: 4 }), g = node('createGain');
    f.frequency.setValueAtTime(700, t); f.frequency.setTargetAtTime(240, t, 0.08);
    env(g, t, 0.005, 0.17, 0.2, 0.11, t + dur, 0.03);
    o.connect(f); sub.connect(g); f.connect(g); g.connect(duck);
    [o, sub].forEach(x => { x.start(t); x.stop(t + dur + 0.2); });
  }
  function keys(t, notes, dur) {
    notes.forEach(m => {
      const o = node('createOscillator', { frequency: N(m) }), o2 = node('createOscillator', { frequency: N(m) * 2.002 }), g2 = node('createGain', { gain: 0.25 }), g = node('createGain');
      env(g, t, 0.005, 0.07, 0.3, 0.02, t + dur, 0.15);
      o.connect(g); o2.connect(g2); g2.connect(g); g.connect(keysBus);
      [o, o2].forEach(x => { x.start(t); x.stop(t + dur + 0.8); });
    });
  }
  function pad(t, notes, dur) {
    notes.forEach(m => [-7, 7].forEach(cents => {
      const o = node('createOscillator', { type: 'sawtooth', frequency: N(m) }), g = node('createGain');
      o.detune.value = cents; env(g, t, 0.7, 0.022, 1, 0.022, t + dur, 0.5);
      o.connect(g); g.connect(padBus); o.start(t); o.stop(t + dur + 2.5);
    }));
  }
  function guitar(t, m, vel, bend, px = (Math.random() - 0.5) * 0.6) {
    const s = node('createBufferSource', { buffer: pluck(m) }), g = node('createGain', { gain: vel * 0.62 });
    if (bend) { s.playbackRate.setValueAtTime(Math.pow(2, -1 / 12), t); s.playbackRate.linearRampToValueAtTime(1, t + 0.08); }
    s.connect(g); pan(g, gHP, px); s.start(t); s.stop(t + 2.4);
  }
  function whistle(t, m, dur, from) {
    const f = N(m), o = node('createOscillator'), g = node('createGain'), lfo = node('createOscillator', { frequency: 5.3 }), depth = node('createGain', { gain: 0 });
    if (from) { o.frequency.setValueAtTime(N(from), t); o.frequency.exponentialRampToValueAtTime(f, t + 0.06); } else o.frequency.setValueAtTime(f, t);
    depth.gain.setValueAtTime(0, t + 0.15); depth.gain.linearRampToValueAtTime(f * 0.009, t + Math.max(0.2, dur * 0.8));
    lfo.connect(depth); depth.connect(o.frequency);
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.11, t + 0.05); g.gain.setValueAtTime(0.11, t + dur); g.gain.linearRampToValueAtTime(0, t + dur + 0.08);
    o.connect(g); pan(g, whistleBus, 0.12);
    const b = node('createBufferSource', { buffer: noise }), bf = node('createBiquadFilter', { type: 'bandpass', frequency: f, Q: 6 }), bg = node('createGain');
    bg.gain.setValueAtTime(0, t); bg.gain.linearRampToValueAtTime(0.05, t + 0.04); bg.gain.setTargetAtTime(0.018, t + 0.05, 0.1); bg.gain.linearRampToValueAtTime(0, t + dur + 0.08);
    b.connect(bf); bf.connect(bg); bg.connect(whistleBus);
    [o, lfo, b].forEach(x => { x.start(t); x.stop(t + dur + 0.12); });
  }
  // Am9 – G6 – Fmaj7 – E7: pad voicings, guitar arpeggios (eighths) and bass roots.
  const CH = [
    { bass: 45, pad: [57, 60, 64, 71], arp: [57, 64, 69, 72, 76, 72, 69, 64] },
    { bass: 43, pad: [55, 59, 62, 64], arp: [55, 62, 67, 71, 74, 71, 67, 62] },
    { bass: 41, pad: [53, 57, 60, 64], arp: [53, 60, 65, 69, 72, 69, 65, 60] },
    { bass: 40, pad: [52, 56, 59, 62], arp: [52, 59, 64, 68, 71, 68, 64, 59] },
  ];
  // The tune (an octave above as a whistle, an octave below on guitar): [bar, beat, beats, midi]
  const TUNE = [[0, 0, 2, 76], [0, 2, 1, 81], [0, 3, 0.5, 79], [0, 3.5, 0.5, 77], [1, 0, 2, 74], [1, 2, 1, 71], [1, 3, 1, 74],
    [2, 0, 1.5, 72], [2, 1.5, 0.5, 69], [2, 2, 1, 72], [2, 3, 1, 77], [3, 0, 3, 76], [3, 3, 1, 68],
    [4, 0, 1, 69], [4, 1, 1, 72], [4, 2, 1.5, 76], [4, 3.5, 0.5, 74], [5, 0, 2, 71], [5, 2, 1, 67], [5, 3, 1, 71],
    [6, 0, 1, 69], [6, 1, 1, 72], [6, 2, 1, 77], [6, 3, 1, 76], [7, 0, 4, 76]];
  const BASS = [[0, 0, 3], [3, 0, 2], [6, 12, 1], [8, 0, 2], [10, 0, 2], [14, 7, 2]];   // [step, interval, steps]
  function scheduleBar(b, t0) {
    const bar = b % SONG.bars, C = CH[bar % 4], T = s => t0 + s * S16, sw = s => T(s) + (s % 2 ? S16 * 0.12 : 0);
    const sec = bar < 8 ? 'intro' : bar < 16 ? 'groove' : bar < 24 ? 'whistle' : bar < 28 ? 'break' : 'return';
    const groove = sec === 'groove' || sec === 'whistle' || sec === 'return';
    pad(t0, C.pad, 4 * SPB);
    if (groove) [0, 4, 8, 12].forEach(s => kick(T(s)));
    else if (sec === 'intro' && bar >= 6) (bar === 6 ? [0, 8] : [0, 4, 8, 12]).forEach(s => kick(T(s)));
    if (groove) {
      [4, 12].forEach(s => clap(T(s)));
      [2, 6, 10, 14].forEach(s => hit(T(s), 'highpass', 7000, 0.7, 0.09, 0.16, 0, -0.2));
      BASS.forEach(([s, iv, n]) => bass(T(s), C.bass + iv, n * S16 * 0.9));
      [3, 10].forEach(s => keys(T(s), C.pad, S16 * 1.6));
    }
    if (sec !== 'intro' || bar >= 4) for (let s = 0; s < 16; s++) hit(sw(s), 'bandpass', 5500, 1.5, s % 4 === 2 ? 0.055 : 0.03, 0.05, 0, 0.3);
    if (sec === 'whistle' || sec === 'break') [0, 3, 6, 8, 11, 14].forEach((s, i) => block(sw(s), i % 2 ? 640 : 900, sec === 'break' ? 0.06 : 0.09, i % 2 ? -0.4 : 0.4));
    // guitar
    if (sec === 'intro' && bar < 4) [0, 8].forEach((s, i) => guitar(T(s), C.arp[i * 4], 0.8, s === 0));
    else if (sec === 'intro' || sec === 'groove') C.arp.forEach((m, i) => guitar(T(i * 2), m, i % 2 ? 0.55 : 0.85, i === 0));
    else if (sec === 'whistle') { if (bar % 4 === 3) [8, 10, 12, 14].forEach((s, i) => guitar(T(s), [64, 68, 71, 74][i], 0.8, i === 0)); else guitar(T(0), C.arp[0], 0.8, true); }
    else if (sec === 'break') [0, 8].forEach(s => guitar(T(s), C.arp[s ? 4 : 2], 0.7, true));
    else { C.arp.forEach((m, i) => guitar(T(i * 2), m - 12, i % 2 ? 0.4 : 0.6, false)); TUNE.filter(n => n[0] === bar - 28).forEach(([, beat, , m]) => guitar(T(beat * 4), m - 12, 1, true)); }
    // whistle
    const tb = sec === 'whistle' ? bar - 16 : sec === 'break' ? bar - 24 + 4 : -1;
    if (tb >= 0) TUNE.forEach(([nb, beat, len, m], i) => { if (nb === tb) whistle(T(beat * 4), m + 12, len * SPB * 0.92, i && TUNE[i - 1][0] === nb && Math.random() < 0.6 ? TUNE[i - 1][3] + 12 : 0); });
  }
  return {
    scheduleBar, barDur: 4 * SPB,
    fade(to, secs) { const t = ctx.currentTime; master.gain.cancelScheduledValues(t); master.gain.setValueAtTime(master.gain.value, t); master.gain.linearRampToValueAtTime(to * 0.6, t + Math.max(0.01, secs)); },
    // Lazy and muffled when idling, opening right up with speed and fully in the air.
    intensity(speed, air) { const k = air ? 1 : Math.min(1, Math.pow(Math.max(0, speed) / 50, 0.7)); tone.frequency.setTargetAtTime(1300 + 16700 * k, ctx.currentTime, 0.4); },
  };
}
const Music = {
  ctx: null, song: null, timer: null, nextBar: 0, nextTime: 0, on: false, lastK: -1,
  get wanted() { try { return localStorage.getItem('rr-music') !== 'off'; } catch (e) { return true; } },
  set wanted(v) { try { localStorage.setItem('rr-music', v ? 'on' : 'off'); } catch (e) {} },
  start() {
    if (this.on) return;
    try { this.ctx = this.ctx || new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return; }
    if (!this.song) this.song = makeSong(this.ctx, this.ctx.destination);
    this.ctx.resume(); this.on = true; this.song.fade(1, 1.5);
    this.nextTime = Math.max(this.nextTime, this.ctx.currentTime + 0.12);
    this.tick(); this.timer = setInterval(() => this.tick(), 60);
  },
  tick() { const ahead = this.ctx.currentTime + 0.5; while (this.nextTime < ahead) { this.song.scheduleBar(this.nextBar++, this.nextTime); this.nextTime += this.song.barDur; } },
  stop() {
    if (!this.on) return;
    this.on = false; clearInterval(this.timer); this.song.fade(0, 0.8);
    setTimeout(() => { if (!this.on && this.ctx) this.ctx.suspend(); }, 900);
  },
  intensity(speed, air) { if (!this.on) return; const k = air ? 2 : Math.round(speed / 3); if (k !== this.lastK) { this.lastK = k; this.song.intensity(speed, air); } },
};
document.addEventListener('visibilitychange', () => { if (Music.on && Music.ctx) document.hidden ? Music.ctx.suspend() : Music.ctx.resume(); });

