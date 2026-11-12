/**
 * The text with `insert` put in place of the selection, and the cursor after it.
 * Used to add a NOTIFY reference to a rule being edited.
 */
export function insertTextAtCursor(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  insert: string,
): { value: string; cursor: number } {
  const start = Math.max(0, Math.min(selectionStart, value.length));
  const end = Math.max(start, Math.min(selectionEnd, value.length));
  return {
    value: value.slice(0, start) + insert + value.slice(end),
    cursor: start + insert.length,
  };
}

/** The DSL text of a NOTIFY action to a Notification Recipient. */
export function notifyRecipientText(name: string): string {
  return `NOTIFY recipient:'${name}'`;
}
