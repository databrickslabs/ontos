/** A save refused for its trigger entity types shows the reason in the user's language (#1151). */
import { afterEach, describe, expect, it } from 'vitest';
import i18n from '@/i18n/config';
import { workflowValidationIssueText } from './step-config-checks';

const unknown = {
  code: 'trigger_entity_type_unknown',
  message: "Unknown entity type 'dataset' on the trigger: remove it to save",
  params: { triggerType: 'before_update', entityType: 'dataset' },
};
const unsupported = {
  code: 'trigger_entity_type_unsupported',
  message: "Trigger 'before_update' never fires for entity type 'data_product'",
  params: { triggerType: 'before_update', entityType: 'data_product' },
};

describe('workflowValidationIssueText: trigger entity types', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('names the unknown type', async () => {
    expect(workflowValidationIssueText(unknown, i18n.t)).toBe(
      'The trigger lists the unknown entity type "dataset": '
      + 'remove it in the trigger settings to save.',
    );
    await i18n.changeLanguage('pt');
    expect(workflowValidationIssueText(unknown, i18n.t)).toBe(
      'O gatilho lista o tipo de entidade desconhecido "dataset": '
      + 'remova-o nas configurações do gatilho para salvar.',
    );
  });

  it('names the trigger and the entity type by their labels', async () => {
    const en = workflowValidationIssueText(unsupported, i18n.t);
    expect(en).toBe(
      `"${i18n.t('common:workflows.triggerTypes.before_update')}" never fires for `
      + `${i18n.t('common:workflows.entityTypes.data_product')}: `
      + 'pick an entity type this trigger supports.',
    );
    expect(en).not.toContain('before_update');
    await i18n.changeLanguage('pt');
    expect(workflowValidationIssueText(unsupported, i18n.t)).toContain('nunca é acionado para');
  });
});
