"use client";

import { animate, createScope } from "animejs";
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { SlideTextLink } from "./motion/SlideTextLink";
import dynamic from "next/dynamic";
import { type ReactNode, useEffect, useRef, useState } from "react";
import styles from "./AgentStory.module.css";
import { AgentIllustration } from "./AgentIllustration";

const AgentWorld = dynamic(() => import("./AgentWorld"), { ssr: false });

const chapters = [
  { name: "Запрос", title: "Начните с задачи", text: "Товар, объём и срок — всё, что нужно для начала подбора.", state: "Поиск", detail: "Потребность покупателя и возможности производства." },
  { name: "Подбор", title: "Найдите подходящее производство", text: "ИИ сопоставляет ваш запрос с товарами и возможностями производителей.", state: "Подбор", detail: "Подбор по характеристикам, объёму и срокам." },
  { name: "Условия", title: "Согласуйте детали", text: "Сравните предложения. Цену, объём и сроки подтверждают обе стороны.", state: "Согласование", detail: "Условия подтверждают покупатель и производитель." },
  { name: "Поставка", title: "От завода — к вашему офису", text: "Производитель готовит партию. Покупатель следит за отгрузкой и подтверждает получение.", state: "Поставка", detail: "Подготовка партии → отгрузка → получение." },
];

export function AgentStory({ landing = false, children }: { landing?: boolean; children?: ReactNode }) {
  const [preview, setPreview] = useState(landing);
  const root = useRef<HTMLDivElement>(null);
  const scene = useRef<HTMLDivElement>(null);
  const controls = useRef<HTMLDivElement>(null);
  const scrollSelection = useRef<number | null>(null);
  const selectionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const selectionFrame = useRef<number | null>(null);
  const [paused, setPaused] = useState(true);
  const [failed3D, setFailed3D] = useState(false);
  const [ready3D, setReady3D] = useState(false);
  const [compact, setCompact] = useState(true);
    const [chapter, setChapter] = useState(0);
  const [staticView, setStaticView] = useState(false);
  const [reduced, setReduced] = useState(false);
  const [insight, setInsight] = useState<"factory" | "buyer" | "agent" | null>(null);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduced(media.matches);
    const viewport = window.matchMedia("(max-width: 650px)");
    const syncViewport = () => setCompact(viewport.matches);
    sync(); syncViewport();
    media.addEventListener("change", sync);
    viewport.addEventListener("change", syncViewport);
    return () => { media.removeEventListener("change", sync); viewport.removeEventListener("change", syncViewport); };
  }, []);

  useEffect(() => {
    if (!root.current || reduced || staticView || paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const scope = createScope({ root: root.current }).add(() => {
      animate('[data-story-action]', { opacity: [.45, 1], translateY: [7, 0], duration: 550, ease: 'out(4)' });
      animate(`[data-chapter="${chapter}"] h2`, { opacity: [.5, 1], translateX: [12, 0], duration: 650, ease: 'out(4)' });
    });
    return () => scope.revert();
  }, [chapter, paused, reduced, staticView]);

  useEffect(() => {
    const header = document.querySelector<HTMLElement>(".site-header");
    const update = () => {
      const headerHeight = header?.getBoundingClientRect().height ?? 0;
      const controlsHeight = controls.current?.getBoundingClientRect().height ?? 0;
      root.current?.style.setProperty("--story-header-height", `${headerHeight}px`);
      root.current?.style.setProperty("--story-scene-top", `${headerHeight + controlsHeight + 12}px`);
    };
    const observer = new ResizeObserver(update);
    if (header) observer.observe(header);
    if (controls.current) observer.observe(controls.current);
    update();
    return () => observer.disconnect();
  }, [staticView, reduced]);

  useEffect(() => {
    const finish = () => {
      scrollSelection.current = null;
      if (selectionTimer.current) clearTimeout(selectionTimer.current);
    };
    const interrupt = () => {
      if (selectionFrame.current !== null) cancelAnimationFrame(selectionFrame.current);
      finish();
    };
    const onKey = (event: KeyboardEvent) => {
      if (["ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End", " "].includes(event.key)) interrupt();
    };
    const onScrollEnd = () => {
      if (scrollSelection.current === null) return;
      const target = root.current?.querySelector<HTMLElement>(`[data-chapter="${scrollSelection.current}"]`);
      const headerHeight = document.querySelector(".site-header")?.getBoundingClientRect().height ?? 0;
      const offset = headerHeight + (controls.current?.getBoundingClientRect().height ?? 0) + 12;
      if (target && Math.abs(target.getBoundingClientRect().top - offset) < 3) finish();
    };
    window.addEventListener("scrollend", onScrollEnd);
    window.addEventListener("wheel", interrupt, { passive: true });
    window.addEventListener("touchstart", interrupt, { passive: true });
    window.addEventListener("keydown", onKey);
    return () => {
      interrupt();
      window.removeEventListener("scrollend", onScrollEnd);
      window.removeEventListener("wheel", interrupt);
      window.removeEventListener("touchstart", interrupt);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => {
    if (staticView || reduced || compact || preview) return;
    let frame = 0;
    const sync = () => {
      frame = 0;
      if (scrollSelection.current !== null || !scene.current) return;
      const bounds = scene.current.getBoundingClientRect();
      const center = bounds.top + bounds.height / 2;
      const sections = Array.from(root.current?.querySelectorAll<HTMLElement>("[data-chapter]") ?? []);
      const closest = sections.reduce<HTMLElement | null>((best, section) => {
        const rect = section.getBoundingClientRect();
        const distance = Math.abs(rect.top + rect.height / 2 - center);
        if (!best) return section;
        const previous = best.getBoundingClientRect();
        return distance < Math.abs(previous.top + previous.height / 2 - center) ? section : best;
      }, null);
      if (closest) setChapter(Number(closest.dataset.chapter));
    };
    const request = () => { if (!frame) frame = requestAnimationFrame(sync); };
    window.addEventListener("scroll", request, { passive: true });
    window.addEventListener("resize", request);
    request();
    return () => { cancelAnimationFrame(frame); window.removeEventListener("scroll", request); window.removeEventListener("resize", request); };
  }, [staticView, reduced, compact, preview]);

  useEffect(() => {
    const element = scene.current;
    if (!element) return;
    let visible = false;
    const sync = () => setPaused(!visible || document.hidden);
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; sync(); });
    observer.observe(element);
    document.addEventListener("visibilitychange", sync);
    return () => { observer.disconnect(); document.removeEventListener("visibilitychange", sync); };
  }, []);

  const still = staticView || reduced;
  const step = still ? 3 : chapter;
  useEffect(() => {
    if (!preview || still) return;
    const timers = [3800, 8500, 13500].map((delay, index) => window.setTimeout(() => setChapter(index + 1), delay));
    const stop = () => { if (window.scrollY > 60) setPreview(false); };
    window.addEventListener("scroll", stop, { passive: true });
    stop();
    return () => { timers.forEach(window.clearTimeout); window.removeEventListener("scroll", stop); };
  }, [preview, still]);

  const selectChapter = (index: number) => {
    scrollSelection.current = index;
    if (selectionTimer.current) clearTimeout(selectionTimer.current);
    if (selectionFrame.current !== null) cancelAnimationFrame(selectionFrame.current);
    setPreview(false);
    setChapter(index);
    if (window.matchMedia("(max-width: 650px)").matches) { scrollSelection.current = null; return; }
    // Wait for all chapters to be laid out after leaving the opening preview.
    selectionFrame.current = requestAnimationFrame(() => {
      selectionFrame.current = requestAnimationFrame(() => {
        const target = root.current?.querySelector<HTMLElement>(`[data-chapter="${index}"]`);
        if (!target) { scrollSelection.current = null; return; }
        const headerHeight = document.querySelector(".site-header")?.getBoundingClientRect().height ?? 0;
        const offset = headerHeight + (controls.current?.getBoundingClientRect().height ?? 0) + 12;
        window.scrollTo({ top: Math.max(0, window.scrollY + target.getBoundingClientRect().top - offset), behavior: reduced ? "instant" : "smooth" });
        let previousY = Number.NaN;
        const releaseWhenSettled = () => {
          const currentY = window.scrollY;
          if (Math.abs(currentY - previousY) < .5) { scrollSelection.current = null; return; }
          previousY = currentY;
          selectionTimer.current = setTimeout(releaseWhenSettled, 100);
        };
        selectionTimer.current = setTimeout(releaseWhenSettled, 1200);
      });
    });
  };

  return <div ref={root} className={`${styles.story} ${landing ? styles.landing : ""}`} data-still={still} data-paused={paused} data-current={step} data-preview={preview && !still}>
    <header className={styles.intro}><span className="eyebrow">Как работает ПоРукам</span><h1>{landing ? <><span className={styles.headlineText}>Товары и <em>производство</em></span></> : <>От запроса <em>к заказу.</em></>}</h1><div className={styles.introBottom}><p>Готовые партии и заказы на производство.</p><SlideTextLink href="/catalog" text="Каталог товаров" /></div></header>
    <div ref={controls} className={styles.controls}><div className={styles.toolbar}><span>От запроса к заказу</span><button type="button" aria-pressed={staticView || reduced} disabled={reduced} onClick={() => setStaticView(!staticView)}>{reduced ? "Движение уменьшено в настройках" : staticView ? "Включить анимацию" : "Без анимации"}</button></div>
    {!still && <LayoutGroup id="story-steps"><nav className={styles.steps} aria-label="Этапы взаимодействия">{chapters.map((item, index) => <button key={item.name} type="button" aria-current={chapter === index ? "step" : undefined} onClick={() => selectChapter(index)}><span>0{index + 1}</span>{" "}{item.name}{chapter === index && <motion.i className={styles.stepIndicator} layoutId="current-step" transition={{ type: "spring", stiffness: 340, damping: 36 }} aria-hidden="true" />}</button>)}</nav></LayoutGroup>}</div>
    <div className={styles.journey}>
      <div ref={scene} className={styles.visual} data-stage={step} data-paused={paused}>
        <div className={styles.horizon} aria-hidden="true" /><div className={styles.grid} aria-hidden="true" />
        <div className={styles.illustration} style={{visibility: ready3D && !still && !failed3D && !compact ? "hidden" : "visible"}}><AgentIllustration stage={step}/></div>
        {!still && !failed3D && !compact && <div className={styles.webgl}><AgentWorld stage={step} paused={paused} onFailure={() => setFailed3D(true)} onReady={() => setReady3D(true)} /></div>}
        <button className={`${styles.hotspot} ${styles.factoryLabel}`} type="button" aria-expanded={insight === "factory"} onClick={() => setInsight(insight === "factory" ? null : "factory")}><small>01 / ПРЕДЛОЖЕНИЕ</small>Завод · продавец <span>+</span></button>
        <button className={`${styles.hotspot} ${styles.buyerLabel}`} type="button" aria-expanded={insight === "buyer"} onClick={() => setInsight(insight === "buyer" ? null : "buyer")}><small>02 / ПОТРЕБНОСТЬ</small>Офис · покупатель <span>+</span></button>
        <button className={styles.agentLabel} type="button" aria-expanded={insight === "agent"} onClick={() => setInsight(insight === "agent" ? null : "agent")}>ИИ-агенты <span aria-hidden="true">+</span></button>
        <AnimatePresence initial={false}>{insight && <motion.div key={insight} initial={still ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: still ? 0 : .2 }} className={styles.insight} role="status">{insight === "factory" ? "Товары, параметры и доступные возможности производства." : insight === "buyer" ? "Требования, количество и срок закупки." : "Подготовка запроса и объяснение подбора. Подтверждают условия стороны."}<button type="button" aria-label="Закрыть пояснение" onClick={() => setInsight(null)}>×</button></motion.div>}</AnimatePresence>
        <div key={step} data-story-action className={styles.stageAction} aria-hidden="true"><span className={styles.actionNumber}>0{step + 1}</span><span>{["Покупатель формирует запрос", "ИИ находит производство", "Стороны согласуют условия", "Партия отправляется покупателю"][step]}</span></div>
        <div className={styles.sceneStatus}><span className={styles.dot} />{chapters[step].detail}</div>
      </div>
      <div className={styles.chapters}>{chapters.map((item, index) => <section key={item.name} id={`story-chapter-${index}`} data-chapter={index} className={styles.chapter}><span className={styles.number}>0{index + 1} / {item.name}</span><h2>{item.title}</h2><p>{item.text}</p>{index === 3 && !landing && <SlideTextLink href="/register" text="Начать сотрудничество" primary />}</section>)}</div>
    </div>

    <noscript><style>{`.${styles.story} .${styles.controls}{display:none}.${styles.story} .${styles.journey}{display:block}.${styles.story} .${styles.visual}{position:relative;top:auto}.${styles.story} .${styles.chapter}{display:flex!important;min-height:0!important}.${styles.story} *{animation:none!important}`}</style></noscript>
    {children}
    <section className={styles.outro}><span className="eyebrow">ПоРукам</span><h2>Что нужно вашему бизнесу?</h2><div className="actions"><SlideTextLink href="/catalog" text="Открыть каталог" /><SlideTextLink href="/needs/new" text="Создать потребность" primary /></div><p>Только российские компании. Расчёты в рублях.</p></section>
  </div>;
}
