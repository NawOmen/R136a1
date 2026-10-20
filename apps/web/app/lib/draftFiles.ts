// Files stay in this browser; keys include the authenticated user and company.
// Persist bytes and metadata rather than native File handles (not portable in WebKit).
interface StoredFile { name: string; type: string; lastModified: number; bytes: ArrayBuffer }
interface StoredFiles { version: 2; files: StoredFile[] }
const pending = new Map<string, Promise<File[]>>();

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("porukam-buyer-drafts", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("files");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function access(key: string, files?: File[] | null): Promise<File[]> {
  // Complete asynchronous reads before opening a transaction: Safari can close an
  // idle transaction while awaiting file.arrayBuffer(). Serialize same-key writes.
  const stored: StoredFiles | undefined = files ? { version: 2, files: await Promise.all(files.map(async file => ({
    name: file.name, type: file.type, lastModified: file.lastModified, bytes: await file.arrayBuffer(),
  }))) } : undefined;
  const db = await database();
  try {
    const value: unknown = await new Promise((resolve, reject) => {
      const transaction = db.transaction("files", files === undefined ? "readonly" : "readwrite");
      const store = transaction.objectStore("files");
      const request = files === undefined ? store.get(key) : files === null ? store.delete(key) : store.put(stored, key);
      transaction.oncomplete = () => resolve(files === undefined ? request.result : undefined);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
    if (files !== undefined) return files ?? [];
    if (Array.isArray(value)) return value.map(file => {
      if (file instanceof File) return file;
      if (file instanceof Blob && typeof (file as File).name === "string") return new File([file], (file as File).name, { type: file.type });
      throw new Error("Не удалось восстановить прежнее вложение. Выберите файл повторно.");
    });
    const record = value as StoredFiles | undefined;
    return record?.version === 2 ? record.files.map(file => new File([file.bytes], file.name, { type: file.type, lastModified: file.lastModified })) : [];
  } finally { db.close(); }
}

export async function draftFiles(key: string, files?: File[] | null): Promise<File[]> {
  const operation = (pending.get(key) ?? Promise.resolve([])).catch(() => []).then(() => access(key, files));
  pending.set(key, operation);
  try { return await operation; }
  finally { if (pending.get(key) === operation) pending.delete(key); }
}
