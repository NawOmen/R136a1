import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Личный кабинет — ПоРукам", description: "Рабочие разделы покупателя и производителя ПоРукам." };

export default function SectionLayout({ children }: { children: ReactNode }) {
  return children;
}
