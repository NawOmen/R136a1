import { legalDocuments } from "../../lib/legalDocuments";
const escape = (value: string) => value.replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]!));
export async function GET(_request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const key = slug.replace(/\.html$/, ""), doc = Object.hasOwn(legalDocuments, key) ? legalDocuments[key] : undefined;
  if (!doc) return new Response("Документ не найден", { status:404 });
  const body = `<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>${escape(doc.title)} — ПоРукам</title><style>body{font:16px/1.8 system-ui;max-width:800px;margin:40px auto;padding:24px;color:#182b3a}h1{line-height:1.2}h2{font-size:21px;margin-top:32px}a{color:#235a88}@media print{body{margin:0;padding:0}}</style><body><p>ПоРукам · Редакция ${escape(doc.version)}</p><h1>${escape(doc.title)}</h1>${doc.sections.map(s=>`<section><h2>${escape(s.title)}</h2><p>${escape(s.text)}</p></section>`).join("")}<h2>Правовые основания</h2><ul>${doc.sources.map(s=>`<li><a href="${escape(s.href)}">${escape(s.title)}</a></li>`).join("")}</ul></body></html>`;
  return new Response(body, { headers: { "Content-Type":"text/html; charset=utf-8", "Content-Disposition":`attachment; filename="porukam-${key}-${doc.version}.html"` } });
}
