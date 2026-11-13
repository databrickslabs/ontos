import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { describeContrast, formatContrastRatio, normalizeHexColor } from '@/lib/branding';
import { cn } from '@/lib/utils';

const FALLBACK_PICKER_COLOR = '#000000';
const HEX_INPUT_MAX_LEN = 7;

interface ThemeColorFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  /** Color used when the field is empty (dark fields: derived from the light one). */
  derived?: string | null;
}

/**
 * One theme color: a native color picker, a hex text input and a live chip
 * showing the text color picked for it and its WCAG contrast.
 */
export function ThemeColorField({
  id,
  label,
  value,
  onChange,
  disabled,
  derived,
}: ThemeColorFieldProps) {
  const { t } = useTranslation('settings');
  const trimmed = value.trim();
  const typed = normalizeHexColor(trimmed);
  const isInvalid = !!trimmed && !typed;
  const isAuto = !trimmed && !!derived;
  const effective = typed || (trimmed ? null : derived || null);
  const contrast = describeContrast(effective);

  return (
    <div className="space-y-2" data-testid={`theme-color-${id}`}>
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-label={t('uiCustomization.theme.pickerLabel', { field: label })}
          value={effective || FALLBACK_PICKER_COLOR}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          className={cn(
            'h-9 w-10 shrink-0 cursor-pointer rounded-md border bg-transparent p-1',
            'disabled:cursor-not-allowed disabled:opacity-50',
          )}
        />
        <Input
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={derived || t('uiCustomization.theme.hexPlaceholder')}
          maxLength={HEX_INPUT_MAX_LEN}
          disabled={disabled}
          aria-invalid={isInvalid}
          className="font-mono"
        />
      </div>
      {isInvalid && (
        <p className="text-sm text-destructive">{t('uiCustomization.theme.invalidColor')}</p>
      )}
      {isAuto && (
        <p className="text-xs text-muted-foreground" data-testid={`theme-color-${id}-auto`}>
          {t('uiCustomization.theme.auto', { color: derived })}
        </p>
      )}
      {effective && contrast && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span
            data-testid={`theme-color-${id}-chip`}
            className={cn(
              'inline-flex h-6 min-w-12 items-center justify-center rounded-md border px-2',
              'font-semibold',
            )}
            style={{ backgroundColor: effective, color: contrast.foregroundHex }}
          >
            Aa
          </span>
          <span data-testid={`theme-color-${id}-contrast`}>
            {t('uiCustomization.theme.contrast', {
              text: t(
                contrast.foreground === 'light'
                  ? 'uiCustomization.theme.textLight'
                  : 'uiCustomization.theme.textDark',
              ),
              ratio: formatContrastRatio(contrast.ratio),
            })}
          </span>
          <span
            className={cn(
              'whitespace-nowrap font-medium',
              contrast.meetsAA ? 'text-green-600 dark:text-green-400' : 'text-destructive',
            )}
          >
            {contrast.meetsAA
              ? t('uiCustomization.theme.meetsAA')
              : t('uiCustomization.theme.belowAA')}
          </span>
        </div>
      )}
    </div>
  );
}

export default ThemeColorField;
