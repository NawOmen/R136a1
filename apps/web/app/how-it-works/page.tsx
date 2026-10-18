import type { Metadata } from "next";
import { AgentStory } from "../components/AgentStory";

export const metadata: Metadata = { title: "Как работает ПоРукам", description: "От потребности до согласованных условий: как ИИ помогает российским компаниям находить друг друга." };

export default function HowItWorksPage() { return <AgentStory />; }
