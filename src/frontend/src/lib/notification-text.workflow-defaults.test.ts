/**
 * Notifications of the default workflows' notification and approval steps
 * carry the keys of their built-in texts (backend:
 * src/common/workflow_notification_texts.py).
 */
import { afterEach, describe, expect, it } from 'vitest';
import i18n from '@/i18n/config';
import { approvalActionPayload, notificationDescription, notificationTitle } from './notification-text';

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

const KEY = 'notifications:workflowDefaults.approval';

// As sent by an approval step for an access request (one line per fact)
const approval = {
  title: 'Approval Required',
  description: [
    'Requester: requester@example.com',
    'Resource: Data Product · Sales Pipeline',
    'Duration: 1 day',
    "Workflow message: Check 'Sales Pipeline' against the runbook.",
    'Note: kept as is',
  ].join('\n'),
  data: {
    i18n: {
      title: `${KEY}.title`,
      descriptionLines: [
        { key: `${KEY}.lines.requester`, text: 'Requester: requester@example.com', params: { requester: 'requester@example.com' } },
        {
          key: `${KEY}.lines.resource`,
          text: 'Resource: Data Product · Sales Pipeline',
          params: {
            resourceType: { key: `${KEY}.entityTypes.data_product`, text: 'Data Product' },
            resourceName: 'Sales Pipeline',
          },
        },
        { key: `${KEY}.lines.duration`, text: 'Duration: 1 day', params: { count: 1 } },
        {
          key: `${KEY}.lines.workflowMessage`,
          text: "Workflow message: Check 'Sales Pipeline' against the runbook.",
          params: { message: "Check 'Sales Pipeline' against the runbook." },
        },
        { text: 'Note: kept as is' },
      ],
    },
  },
};

describe('approval notifications', () => {
  afterEach(() => {
    i18n.changeLanguage('en');
  });

  it('shows each line in the user language', async () => {
    expect(notificationTitle(approval, t)).toBe('Approval Required');
    expect(notificationDescription(approval, t)).toBe(approval.description);

    await i18n.changeLanguage('pt');
    expect(notificationTitle(approval, t)).toBe('Aprovação necessária');
    expect(notificationDescription(approval, t)).toBe([
      'Solicitante: requester@example.com',
      'Recurso: Produto de dados · Sales Pipeline',
      'Duração: 1 dia',
      "Mensagem do workflow: Check 'Sales Pipeline' against the runbook.",
      'Note: kept as is',
    ].join('\n'));

    await i18n.changeLanguage('de');
    expect(notificationDescription(approval, t).split('\n')[2]).toBe('Dauer: 1 Tag');
  });

  it('falls back to the English text of a line without a translation', async () => {
    await i18n.changeLanguage('pt');
    const unknownKey = {
      ...approval,
      data: { i18n: { descriptionLines: [{ key: `${KEY}.lines.notAKey`, text: 'Requester: x' }] } },
    };
    expect(notificationDescription(unknownKey, t)).toBe('Requester: x');
  });
});

describe('entity types in default workflow notifications', () => {
  afterEach(() => {
    i18n.changeLanguage('en');
  });

  // As sent by the Validation workflow's notify step: the type comes raw
  const validationFailed = {
    title: 'Validation Failed',
    description: "Validation failed for data_product 'orders'",
    data: {
      i18n: {
        title: 'notifications:workflowDefaults.templates.validation_failed.title',
        description: 'notifications:workflowDefaults.templates.validation_failed.message',
        params: { entity_type: 'data_product', entity_name: 'orders' },
      },
    },
  };

  it('shows the entity type label instead of the raw type', async () => {
    expect(notificationDescription(validationFailed, t)).toBe(
      "Validation failed for Data Product 'orders'",
    );
    await i18n.changeLanguage('pt');
    expect(notificationDescription(validationFailed, t)).toBe(
      "A validação falhou para Produto de dados 'orders'",
    );
  });

  it('falls back to the raw type for an unknown one', () => {
    const unknown = {
      ...validationFailed,
      data: { i18n: { ...validationFailed.data.i18n, params: { entity_type: 'gizmo', entity_name: 'x' } } },
    };
    expect(notificationDescription(unknown, t)).toBe("Validation failed for gizmo 'x'");
  });
});

describe('approval dialog payload', () => {
  afterEach(() => {
    i18n.changeLanguage('en');
  });

  const message = (extra: Record<string, unknown> = {}) => ({
    title: 'Approval Required',
    description: '',
    action_payload: {
      execution_id: 'x1',
      workflow_message: "Please review the certification request for data_product 'Orders'.",
    },
    data: {
      i18n: {
        title: 'notifications:workflowDefaults.approval.title',
        descriptionLines: [{
          key: 'notifications:workflowDefaults.approval.lines.workflowMessage',
          text: 'Workflow message: x',
          params: {
            message: {
              key: 'notifications:workflowDefaults.approvalMessages.certification-request-review.approval-gate',
              text: "Please review the certification request for data_product 'Orders'.",
              params: { entity_type: 'data_product', entity_name: 'Orders' },
              ...extra,
            },
          },
        }],
      },
    },
  });

  it('shows the shipped message with the entity type label', async () => {
    expect(approvalActionPayload(message(), t)?.workflow_message).toBe(
      "Please review the certification request for Data Product 'Orders'.",
    );
    await i18n.changeLanguage('pt');
    expect(approvalActionPayload(message(), t)?.workflow_message).toBe(
      "Revise a solicitação de certificação de Produto de dados 'Orders'.",
    );
  });

  it('keeps the stored message when the notification has no key for it', () => {
    const edited = { ...message(), data: { i18n: { title: 'notifications:workflowDefaults.approval.title' } } };
    expect(approvalActionPayload(edited, t)).toBe(edited.action_payload);
    const plain = { title: 'Approval Required', description: '', action_payload: { execution_id: 'x1' } };
    expect(approvalActionPayload(plain, t)).toBe(plain.action_payload);
  });
});
