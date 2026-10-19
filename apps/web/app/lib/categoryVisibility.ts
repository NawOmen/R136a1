/** New marketplace choices exclude these branches; historical profiles remain readable. */
export function isVisibleCategory(category: string): boolean {
  return !["Продукты питания", "Медицина и гигиена"].includes(category);
}
