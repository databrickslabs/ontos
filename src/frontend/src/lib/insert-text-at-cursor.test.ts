import { describe, expect, it } from 'vitest';

import { insertTextAtCursor, notifyRecipientText } from './insert-text-at-cursor';

describe('insertTextAtCursor', () => {
  it('replaces the selection and puts the cursor after the inserted text', () => {
    expect(insertTextAtCursor('ON_FAIL FAIL', 8, 12, 'NOTIFY x')).toEqual({
      value: 'ON_FAIL NOTIFY x',
      cursor: 16,
    });
  });

  it('inserts at the end when the cursor is past the text', () => {
    expect(insertTextAtCursor('a', 9, 9, 'b')).toEqual({ value: 'ab', cursor: 2 });
  });
});

describe('notifyRecipientText', () => {
  it('quotes the recipient name, so names with spaces parse', () => {
    expect(notifyRecipientText('Data Stewards')).toBe("NOTIFY recipient:'Data Stewards'");
  });
});
