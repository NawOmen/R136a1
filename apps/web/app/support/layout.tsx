import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Поддержка — ПоРукам", description: "Чат с командой ПоРукам: вопросы и история переписки." };

export default function SectionLayout({ children }: { children: ReactNode }) {
  return children;
}
