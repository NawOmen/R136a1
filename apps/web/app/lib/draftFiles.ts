// Files stay in this browser; keys include the authenticated user and company.
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("porukam-buyer-drafts", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("files");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function draftFiles(key: string, files?: File[] | null): Promise<File[]> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction("files", files === undefined ? "readonly" : "readwrite");
      const store = transaction.objectStore("files");
      const request = files === undefined ? store.get(key) : files === null ? store.delete(key) : store.put(files, key);
      transaction.oncomplete = () => resolve(files === undefined ? request.result ?? [] : files ?? []);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally { db.close(); }
}
