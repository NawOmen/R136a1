import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Поддержка — ПоРукам", description: "Обращения в поддержку ПоРукам: номер, статус и ответ администратора." };

export default function SectionLayout({ children }: { children: ReactNode }) {
  return children;
}
