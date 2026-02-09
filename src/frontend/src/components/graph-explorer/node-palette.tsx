import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { PlusCircle, Link } from 'lucide-react';

interface NodePaletteProps {
  onStartCreateNode?: () => void;
  onStartCreateEdge: () => void;
  disabled?: boolean;
}

export default function NodePalette({
  onStartCreateNode,
  onStartCreateEdge,
  disabled = false,
}: NodePaletteProps) {
  const { t } = useTranslation('graph-explorer');

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle>{t('palette.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Create Node Button */}
        <Button
          onClick={onStartCreateNode}
          disabled={disabled || !onStartCreateNode}
          className="w-full"
          size="lg"
        >
          <PlusCircle className="mr-2 h-5 w-5" />
          {t('actions.createNode')}
        </Button>

        <Separator />

        {/* Relationships Section */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Link className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-base">{t('palette.relationships')}</CardTitle>
          </div>
          <Button
            onClick={onStartCreateEdge}
            disabled={disabled}
            variant="outline"
            className="w-full"
          >
            <Link className="mr-2 h-4 w-4" />
            {t('actions.createEdge')}
          </Button>
        </div>

        <Separator />

        {/* Instructions */}
        <div className="space-y-3">
          <CardTitle className="text-base">{t('palette.instructions')}</CardTitle>
          <div className="space-y-2 text-sm text-muted-foreground">
            <div className="flex items-start gap-2">
              <span className="font-semibold text-foreground">1.</span>
              <span>{t('palette.step1')}</span>
            </div>
            <div className="flex items-start gap-2">
              <span className="font-semibold text-foreground">2.</span>
              <span>{t('palette.step2')}</span>
            </div>
            <div className="flex items-start gap-2">
              <span className="font-semibold text-foreground">3.</span>
              <span>{t('palette.step3')}</span>
            </div>
            <div className="flex items-start gap-2">
              <span className="font-semibold text-foreground">4.</span>
              <span>{t('palette.step4')}</span>
            </div>
          </div>
        </div>

        <Separator />

        {/* Tip Box */}
        <div className="rounded-lg bg-muted/50 p-3">
          <div className="text-xs font-semibold text-foreground mb-1">{t('palette.tip')}</div>
          <div className="text-xs text-muted-foreground">
            {t('palette.tipText')}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
