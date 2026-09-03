"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

export function OnboardingTour({ canBuy, canSell }: { canBuy: boolean; canSell: boolean }) {
  const [open, setOpen] = useState(false); const [step, setStep] = useState(0);
  useEffect(() => { setOpen(window.localStorage.getItem("porukam-onboarding-complete") !== "yes"); }, []);
  const steps = [
    { title: "Выберите рабочий путь", body: canBuy && canSell ? "Одна компания может одновременно покупать и продавать. Режим меняет только рабочие инструменты." : canBuy ? "Начните с каталога или создайте карточку потребности." : canSell ? "Заполните паспорт производства и опубликуйте товар." : "Сначала создайте компанию и выберите права покупки или продажи.", href: "/dashboard", action: "Понятно" },
    { title: "Заполните данные компании", body: "Публикация и сделки станут доступны после проверки. В демо используются только синтетические данные.", href: "/company/new", action: "К компании" },
    { title: "Совершите первое действие", body: canSell ? "Добавьте товар или посмотрите подтверждённый спрос покупателей." : "Опишите потребность голосом или текстом — агент подготовит требования.", href: canSell ? "/seller/products" : "/needs/new", action: "Начать" },
  ];
  function finish() { window.localStorage.setItem("porukam-onboarding-complete", "yes"); setOpen(false); }
  if (!open) return <button className="onboarding-reopen" onClick={() => { setStep(0); setOpen(true); }}>Первые шаги</button>;
  const item = steps[step];
  return <div className="tour"><span className="eyebrow">Первые шаги · {step + 1} из {steps.length}</span><h2>{item.title}</h2><p>{item.body}</p><div className="actions">{step < steps.length - 1 ? <button className="btn btn-primary" onClick={() => setStep(step + 1)}>Далее</button> : <Link className="btn btn-primary" href={item.href} onClick={finish}>{item.action}</Link>}<button className="btn btn-secondary" onClick={finish}>Пропустить</button></div></div>;
}
