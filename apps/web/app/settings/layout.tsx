import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Настройки — ПоРукам", description: "Тема интерфейса и подписки на изменения российского рынка для бизнеса." };

export default function SectionLayout({ children }: { children: ReactNode }) {
  return children;
}
