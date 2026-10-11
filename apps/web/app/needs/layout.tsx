import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Потребности — ПоРукам", description: "Создание и повтор закупки у российских производителей." };

export default function SectionLayout({ children }: { children: ReactNode }) {
  return children;
}
