import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';

/** Authority Relations | Authority Policies, shown on both list views. */
export default function AuthorityNav({ current }: { current: 'relations' | 'policies' }) {
  const { t } = useTranslation(['authority-resolution']);
  const navigate = useNavigate();
  return (
    <Tabs
      value={current}
      onValueChange={(v) => navigate(v === 'policies' ? '/authority-resolution/policies' : '/authority-resolution')}
      className="mb-6"
    >
      <TabsList>
        <TabsTrigger value="relations">{t('nav.relations')}</TabsTrigger>
        <TabsTrigger value="policies">{t('nav.policies')}</TabsTrigger>
      </TabsList>
    </Tabs>
  );
}
