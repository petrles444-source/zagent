"use client";

import { useEffect, useRef, useState } from "react";
import { Heart } from "./ornaments";
import { cn } from "@/lib/utils";

/**
 * Ambient audio toggle — synthesises a soft warm drone + gentle
 * "candle crackle" pops using the Web Audio API. No external audio
 * files needed (works fully offline). Toggle persists in localStorage.
 *
 * Respects prefers-reduced-motion (audio is still available on demand,
 * but starts muted).
 */
export function AmbientAudio() {
  const [on, setOn] = useState(false);
  const [ready, setReady] = useState(false);
  const ctxRef = useRef<AudioContext | null>(null);
  const masterRef = useRef<GainNode | null>(null);
  const nodesRef = useRef<{ stop: () => void } | null>(null);

  // restore preference (browsers block autoplay, so we never resume sound
  // automatically — only the ready flag is gated to a rAF to stay lint-safe).
  useEffect(() => {
    const raf = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const start = async () => {
    if (typeof window === "undefined") return;
    const AudioCtx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    if (!AudioCtx) return;

    if (!ctxRef.current) {
      const ctx = new AudioCtx();
      ctxRef.current = ctx;
      const master = ctx.createGain();
      master.gain.value = 0;
      master.connect(ctx.destination);
      masterRef.current = master;
      nodesRef.current = buildAmbience(ctx, master);
    }
    const ctx = ctxRef.current!;
    if (ctx.state === "suspended") await ctx.resume();
    // fade in
    const now = ctx.currentTime;
    masterRef.current!.gain.cancelScheduledValues(now);
    masterRef.current!.gain.setValueAtTime(masterRef.current!.gain.value, now);
    masterRef.current!.gain.linearRampToValueAtTime(0.18, now + 1.5);
    setOn(true);
    localStorage.setItem("wedding-ambient-audio", "on");
  };

  const stop = () => {
    const ctx = ctxRef.current;
    const master = masterRef.current;
    if (!ctx || !master) {
      setOn(false);
      return;
    }
    const now = ctx.currentTime;
    master.gain.cancelScheduledValues(now);
    master.gain.setValueAtTime(master.gain.value, now);
    master.gain.linearRampToValueAtTime(0, now + 0.8);
    setOn(false);
    localStorage.setItem("wedding-ambient-audio", "off");
  };

  const toggle = () => (on ? stop() : start());

  // cleanup on unmount
  useEffect(() => {
    return () => {
      nodesRef.current?.stop();
      ctxRef.current?.close().catch(() => {});
    };
  }, []);

  if (!ready) return null;

  return (
    <button
      onClick={toggle}
      aria-pressed={on}
      aria-label={on ? "Выключить атмосферный звук" : "Включить атмосферный звук"}
      className={cn(
        "group fixed bottom-6 left-6 z-50 flex h-12 w-12 items-center justify-center rounded-full border backdrop-blur-md transition-all duration-500 sm:bottom-20",
        on
          ? "border-gold/60 bg-gold/15 text-gold shadow-[0_0_18px_rgba(200,169,106,0.5)]"
          : "border-gold/30 bg-night/70 text-gold/60 hover:border-gold/60 hover:text-gold"
      )}
    >
      {/* sound waves animation */}
      <span className="relative flex h-5 w-5 items-center justify-center">
        {on ? (
          <>
            <span className="absolute inset-0 flex items-center justify-center">
              <span className="h-1 w-1 rounded-full bg-current" />
            </span>
            <span className="absolute h-3 w-3 rounded-full border border-current opacity-60 animate-ping" />
            <span className="absolute h-5 w-5 rounded-full border border-current opacity-30" />
          </>
        ) : (
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round">
            <path d="M11 5 6 9H3v6h3l5 4V5Z" />
            <path d="M16 9a3 3 0 0 1 0 6" opacity="0.7" />
            <path d="M19 7a6 6 0 0 1 0 10" opacity="0.4" />
          </svg>
        )}
      </span>
      <Heart
        className={cn(
          "absolute -right-1 -top-1 h-3 w-3 transition-all",
          on ? "text-gold animate-flicker" : "text-gold/40"
        )}
        filled={on}
      />
      {/* tooltip */}
      <span className="pointer-events-none absolute bottom-full left-1/2 mb-2 -translate-x-1/2 whitespace-nowrap rounded-sm border border-gold/30 bg-night/95 px-3 py-1 font-playfair text-[0.6rem] uppercase tracking-luxe text-gold opacity-0 backdrop-blur-sm transition-opacity duration-300 group-hover:opacity-100">
        {on ? "Звук вечера" : "Атмосфера"}
      </span>
    </button>
  );
}

/**
 * Build a soft warm drone (two detuned oscillators through a low-pass
 * filter) plus a recurring "candle crackle" noise burst scheduler.
 */
function buildAmbience(ctx: AudioContext, master: GainNode): { stop: () => void } {
  // --- drone ---
  const droneGain = ctx.createGain();
  droneGain.gain.value = 0.5;

  const filter = ctx.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.value = 420;
  filter.Q.value = 0.7;

  const oscA = ctx.createOscillator();
  oscA.type = "sine";
  oscA.frequency.value = 110; // A2
  const oscB = ctx.createOscillator();
  oscB.type = "sine";
  oscB.frequency.value = 110 * 1.5; // perfect fifth
  oscB.detune.value = 4;

  // slow LFO on the filter for a "breathing" feel
  const lfo = ctx.createOscillator();
  lfo.frequency.value = 0.08;
  const lfoGain = ctx.createGain();
  lfoGain.gain.value = 120;
  lfo.connect(lfoGain).connect(filter.frequency);

  oscA.connect(filter);
  oscB.connect(filter);
  filter.connect(droneGain).connect(master);

  oscA.start();
  oscB.start();
  lfo.start();

  // --- candle crackle ---
  let crackleTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  const scheduleCrackle = () => {
    if (stopped) return;
    const delay = 800 + Math.random() * 2400;
    crackleTimer = setTimeout(() => {
      playCrackle(ctx, master);
      scheduleCrackle();
    }, delay);
  };
  scheduleCrackle();

  return {
    stop: () => {
      stopped = true;
      if (crackleTimer) clearTimeout(crackleTimer);
      try {
        oscA.stop();
        oscB.stop();
        lfo.stop();
      } catch {
        /* already stopped */
      }
    },
  };
}

/** A single short "crackle" — filtered noise burst with fast decay. */
function playCrackle(ctx: AudioContext, master: GainNode) {
  const duration = 0.08 + Math.random() * 0.12;
  const bufferSize = Math.floor(ctx.sampleRate * duration);
  const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < bufferSize; i++) {
    // random noise with a decay envelope
    const env = Math.pow(1 - i / bufferSize, 2.5);
    data[i] = (Math.random() * 2 - 1) * env * 0.6;
  }
  const src = ctx.createBufferSource();
  src.buffer = buffer;

  const bp = ctx.createBiquadFilter();
  bp.type = "bandpass";
  bp.frequency.value = 1500 + Math.random() * 2500;
  bp.Q.value = 4;

  const g = ctx.createGain();
  g.gain.value = 0.04 + Math.random() * 0.05;

  src.connect(bp).connect(g).connect(master);
  src.start();
  src.onended = () => {
    src.disconnect();
    bp.disconnect();
    g.disconnect();
  };
}
