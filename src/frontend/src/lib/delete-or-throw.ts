/**
 * `useApi().delete` resolves with `{ error }` on HTTP errors instead of throwing.
 * Delete call sites rely on try/catch to show the error toast and
 * to skip navigation / success toasts, so convert a failed response into a throw.
 */
export async function deleteOrThrow(
  deleteFn: (url: string) => Promise<{ error?: string | null }>,
  url: string,
): Promise<void> {
  const res = await deleteFn(url);
  if (res.error) throw new Error(res.error);
}
