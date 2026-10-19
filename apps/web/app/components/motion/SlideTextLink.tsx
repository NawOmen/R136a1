"use client";

// Adapted from Kokonut UI slide-text-button (MIT), © 2025 kokonutUI.
// License: apps/web/licenses/Kokonut-UI-MIT.txt.
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";

const MotionLink = motion.create(Link);
export function SlideTextLink({ href, text, primary = false }: { href: string; text: string; primary?: boolean }) {
  const reduced = useReducedMotion();
  return <MotionLink href={href} className={`btn ${primary ? "btn-primary" : "btn-secondary"} slide-text-link`} whileTap={reduced ? undefined : { scale: .975 }} transition={{ type: "spring", stiffness: 420, damping: 32 }}>
    <span className="slide-text-link__track"><span>{text}<span aria-hidden="true"> →</span></span><span aria-hidden="true">{text} →</span></span>
  </MotionLink>;
}
