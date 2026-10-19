"use client";

// Adapted from Kokonut UI ai-text-loading (MIT), © 2025 kokonutUI.
// Retains its staggered opacity wave, with one truthful status instead of fake progress.
export function LoadingText({ text }: { text: string }) {
  return <span className="loading-wave" aria-hidden="true"><span aria-hidden="true">{Array.from(text).map((letter, index) => <span key={index} style={{ animationDelay: `${index * .035}s` }}>{letter === " " ? "\u00a0" : letter}</span>)}</span></span>;
}
