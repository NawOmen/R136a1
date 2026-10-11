import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Помощь и база знаний — ПоРукам", description: "Справка о работе ПоРукам, локальный помощник и переход в поддержку." };

export default function SectionLayout({ children }: { children: ReactNode }) {
  return children;
}
