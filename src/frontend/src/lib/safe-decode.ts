/**
 * decodeURIComponent that returns the raw value when it is not valid percent-encoding
 * (e.g. a hand-edited or truncated link such as `#%E0%A4%A`) instead of throwing a URIError.
 */
export function safeDecodeURIComponent(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
