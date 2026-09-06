import { useTranslation } from 'react-i18next';
import { ExternalLink } from 'lucide-react';

// ---------------------------------------------------------------------------
// Deliver lane — Direct / Indirect / Manual mode cards (ADVANCED-ONLY).
//
// These map to Ontos' real Delivery Mode concept (Direct = SP applies changes
// immediately; Indirect = writes YAML to Git for a CI/CD pipeline to promote;
// Manual = notifies a person to apply elsewhere). Mode is configured per site
// under Settings > Delivery (settings-delivery), NOT per concept — so these
// cards are a read-only summary with a link out, matching the wireframe.
//
// We show which mode(s) are "active" from a passed-in prop rather than
// asserting a default; the caller decides based on real config when available.
// ---------------------------------------------------------------------------

export type DeliveryMode = 'direct' | 'indirect' | 'manual';

interface Props {
  /** Modes currently configured as active for the selected site. */
  activeModes?: DeliveryMode[];
  /** Link to the per-site delivery settings. */
  settingsHref?: string;
}

export default function DeliveryModes({
  activeModes = [],
  settingsHref = '/settings/delivery',
}: Props) {
  const { t } = useTranslation(['concepts', 'common']);

  const modes: { id: DeliveryMode; label: string; desc: string }[] = [
    {
      id: 'direct',
      label: t('enrich.modes.direct', 'Direct'),
      desc: t(
        'enrich.modes.directDesc',
        'Ontos applies changes to this workspace immediately via the service principal.',
      ),
    },
    {
      id: 'indirect',
      label: t('enrich.modes.indirect', 'Indirect'),
      desc: t(
        'enrich.modes.indirectDesc',
        'Ontos writes YAML to Git for your CI/CD pipeline to promote (dev to staging to prod).',
      ),
    },
    {
      id: 'manual',
      label: t('enrich.modes.manual', 'Manual'),
      desc: t('enrich.modes.manualDesc', 'Ontos notifies a person to apply the change elsewhere.'),
    },
  ];

  return (
    <div className="mb-3.5 flex flex-wrap items-stretch gap-2.5">
      {modes.map((mode) => {
        const active = activeModes.includes(mode.id);
        return (
          <div
            key={mode.id}
            className={`min-w-[180px] flex-1 rounded-lg border px-3.5 py-3 ${
              active
                ? 'border-emerald-500/50 bg-emerald-500/5'
                : 'border-border bg-card'
            }`}
          >
            <div className="mb-1 flex items-center gap-2 text-sm">
              <span
                className={`h-2 w-2 rounded-full ${active ? 'bg-emerald-500' : 'bg-border'}`}
              />
              <b>{mode.label}</b>
              {active && (
                <span className="ml-auto rounded-full bg-emerald-500/12 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400">
                  {t('enrich.modes.active', 'active')}
                </span>
              )}
            </div>
            <p className="text-xs leading-snug text-muted-foreground">{mode.desc}</p>
          </div>
        );
      })}
      <a
        href={settingsHref}
        className="inline-flex basis-full items-center gap-1 text-xs text-sky-700 hover:underline dark:text-sky-400"
      >
        {t('enrich.modes.manageLink', 'Delivery mode is set per site in Settings, Delivery')}
        <ExternalLink className="h-3 w-3" />
      </a>
    </div>
  );
}
