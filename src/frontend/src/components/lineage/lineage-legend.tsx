/**
 * Collapsible legend overlay for the column-based lineage view.
 */



import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { X } from 'lucide-react';
import { TYPE_COLOR } from './constants';

interface LineageLegendProps {
  onClose: () => void;
}

export default function LineageLegend({ onClose }: LineageLegendProps) {
  const { t } = useTranslation(['data-catalog', 'common']);
  const typeEntries = Object.entries(TYPE_COLOR);

  return (
    <div className="absolute bottom-4 right-4 z-10 w-56 rounded-lg border bg-card/95 backdrop-blur-sm shadow-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{t('common:labels.legend')}</span>
        <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={onClose}>
          <X className="h-3 w-3" />
        </Button>
      </div>

      {/* Entity types */}
      <div className="space-y-1 mb-3">
        <p className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider mb-1">{t('data-catalog:lineage.legendPanel.entityTypes')}</p>
        <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
          {typeEntries.map(([type, colors]) => (
            <div key={type} className="flex items-center gap-1.5">
              <div
                className="w-2.5 h-2.5 rounded-full shrink-0"
                style={{ backgroundColor: colors.hex }}
              />
              <span className="text-[10px] text-muted-foreground truncate">
                {type.replace(/([A-Z])/g, ' $1').trim()}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Edge styles */}
      <div className="space-y-1.5 pt-2 border-t">
        <p className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider mb-1">{t('data-catalog:lineage.legendPanel.edgeStyles')}</p>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="w-8 h-0 border-t-2 border-foreground/60" />
            <span className="text-[10px] text-muted-foreground">{t('data-catalog:lineage.legendPanel.dataFlow')}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-0 border-t-[1.5px] border-muted-foreground/40" />
            <span className="text-[10px] text-muted-foreground">{t('data-catalog:lineage.legendPanel.containment')}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-0 border-t-[1.5px] border-dashed border-muted-foreground/60" />
            <span className="text-[10px] text-muted-foreground">{t('data-catalog:lineage.legendPanel.governance')}</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-0 border-t border-dotted border-muted-foreground/40" />
            <span className="text-[10px] text-muted-foreground">{t('data-catalog:lineage.legendPanel.semantic')}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
