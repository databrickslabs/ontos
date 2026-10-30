import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import i18next from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';

import en from '@/i18n/locales/en/access-policies.json';
import ja from '@/i18n/locales/ja/access-policies.json';
import RuleSentence from './rule-sentence';

const i18n = i18next.createInstance();
i18n.use(initReactI18next).init({
  lng: 'en',
  resources: { en: { 'access-policies': en }, ja: { 'access-policies': ja } },
  interpolation: { escapeValue: false }, // as in the app (React escapes)
});

const sentence = (lng: string, props: Parameters<typeof RuleSentence>[0]) => {
  i18n.changeLanguage(lng);
  return render(
    <I18nextProvider i18n={i18n}>
      <RuleSentence {...props} />
    </I18nextProvider>,
  ).container;
};

describe('RuleSentence', () => {
  it('renders names with markup characters as text', () => {
    const el = sentence('en', { kind: 'permission', assignee: 'a<b>&c', action: 'Read', target: 'uc:main.<tmp>' });
    expect(el.textContent).toBe('a<b>&c may Read on uc:main.<tmp>');
    expect(el.querySelector('code')?.textContent).toBe('uc:main.<tmp>');
    expect(el.querySelectorAll('strong')[0].textContent).toBe('a<b>&c');
  });

  it('lets each language order the parts', () => {
    const el = sentence('ja', { kind: 'prohibition', assignee: 'Sales', action: 'Modify', target: 'uc:x' });
    expect(el.textContent).toBe('Salesはuc:xに対してModifyが禁止されています');
  });

  it('has a sentence without a target', () => {
    expect(sentence('en', { kind: 'obligation', assignee: 'Everyone', action: 'Acknowledge' }).textContent).toBe(
      'Everyone must Acknowledge',
    );
  });
});
