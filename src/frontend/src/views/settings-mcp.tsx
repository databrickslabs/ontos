import SettingsPageWrapper from '@/components/settings/settings-page-wrapper';
import MCPTokensSettings from '@/components/settings/mcp-tokens-settings';
import { useTranslation } from 'react-i18next';

export default function SettingsMcpView() {
  const { t } = useTranslation(['settings']);
  return (
    <SettingsPageWrapper title={t('settings:tabs.mcpTokens', 'MCP Tokens')} permissionId="settings-mcp">
      <MCPTokensSettings />
    </SettingsPageWrapper>
  );
}
