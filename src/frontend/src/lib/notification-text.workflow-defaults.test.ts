/**
 * Notifications of the default workflows' notification steps carry the keys
 * of their built-in texts (backend: src/common/workflow_notification_texts.py).
 */
import { afterEach, describe, expect, it } from 'vitest';
import i18n from '@/i18n/config';
import { notificationDescription, notificationTitle } from './notification-text';

const t = i18n.t.bind(i18n);

// As sent by the Contract Deploy Request workflow's notify-approved step
const deployApproved = {
  title: 'Request Approved',
  description: "Your request to deploy the data contract 'orders' has been approved.",
  data: {
    i18n: {
      title: 'notifications:workflowDefaults.templates.request_approved.title',
      description: 'notifications:workflowDefaults.messages.contract-deploy-request.notify-approved',
      params: { entity_name: 'orders' },
    },
  },
};

// A message an admin changed: only the title has a key
const edited = {
  title: 'Request Approved',
  description: "Deploy of 'orders' approved, see the runbook.",
  data: { i18n: { title: 'notifications:workflowDefaults.templates.request_approved.title' } },
};

describe('default workflow notifications', () => {
  afterEach(() => {
    i18n.changeLanguage('en');
  });

  it('shows the shipped texts in the user language', async () => {
    expect(notificationTitle(deployApproved, t)).toBe('Request Approved');
    expect(notificationDescription(deployApproved, t)).toBe(deployApproved.description);

    await i18n.changeLanguage('pt');
    expect(notificationTitle(deployApproved, t)).toBe('Solicitação aprovada');
    expect(notificationDescription(deployApproved, t)).toBe(
      "Sua solicitação para implantar o contrato de dados 'orders' foi aprovada.",
    );
  });

  it('shows an edited message as written', async () => {
    await i18n.changeLanguage('pt');
    expect(notificationTitle(edited, t)).toBe('Solicitação aprovada');
    expect(notificationDescription(edited, t)).toBe(edited.description);
  });
});
