import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { useToast } from '@/hooks/use-toast';
import { usePermissions } from '@/stores/permissions-store';
import { FeatureAccessLevel } from '@/types/settings';
import {
  Palette,
  Languages,
  Image,
  FileText,
  Code,
  Loader2,
  Save,
  AlertTriangle,
  Eye,
  RotateCcw,
  ExternalLink,
  Tag,
} from 'lucide-react';
import MarkdownViewer from '@/components/ui/markdown-viewer';
import { useUICustomizationStore } from '@/stores/ui-customization-store';
import {
  CardSkeleton,
  SkeletonLine,
} from '@/components/common/list-view-skeleton';
import { DEFAULT_APP_NAME } from '@/lib/branding';

const APP_DISPLAY_NAME_MAX_LEN = 64;
const APP_SHORT_NAME_MAX_LEN = 16;

interface UICustomizationState {
  i18nEnabled: boolean;
  customLogoUrl: string;
  aboutContent: string;
  customCss: string;
  appDisplayName: string;
  appShortName: string;
  faviconUrl: string;
}

export default function UICustomizationSettings() {
  const { t } = useTranslation(['settings', 'common']);
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const hasWriteAccess = hasPermission('settings-ui', FeatureAccessLevel.READ_WRITE);
  const refreshBranding = useUICustomizationStore((s) => s.fetchSettings);

  const [settings, setSettings] = useState<UICustomizationState>({
    i18nEnabled: true,
    customLogoUrl: '',
    aboutContent: '',
    customCss: '',
    appDisplayName: '',
    appShortName: '',
    faviconUrl: '',
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [previewTab, setPreviewTab] = useState<'edit' | 'preview'>('edit');
  const [logoError, setLogoError] = useState(false);
  const [faviconError, setFaviconError] = useState(false);

  useEffect(() => {
    const fetchSettings = async () => {
      setIsLoading(true);
      try {
        const response = await fetch('/api/settings');
        if (response.ok) {
          const data = await response.json();
          setSettings({
            i18nEnabled: data.ui_i18n_enabled ?? true,
            customLogoUrl: data.ui_custom_logo_url || '',
            aboutContent: data.ui_about_content || '',
            customCss: data.ui_custom_css || '',
            appDisplayName: data.ui_app_display_name || '',
            appShortName: data.ui_app_short_name || '',
            faviconUrl: data.ui_favicon_url || '',
          });
        }
      } catch (error) {
        console.error('Failed to fetch settings:', error);
      } finally {
        setIsLoading(false);
      }
    };
    fetchSettings();
  }, []);

  const handleSaveSettings = async () => {
    setIsSaving(true);
    try {
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ui_i18n_enabled: settings.i18nEnabled,
          ui_custom_logo_url: settings.customLogoUrl || null,
          ui_about_content: settings.aboutContent || null,
          ui_custom_css: settings.customCss || null,
          ui_app_display_name: settings.appDisplayName.trim() || null,
          ui_app_short_name: settings.appShortName.trim() || null,
          ui_favicon_url: settings.faviconUrl || null,
        }),
      });
      if (response.ok) {
        toast({
          title: t('settings:uiCustomization.messages.saveSuccess', 'UI customization settings saved'),
          description: t('settings:uiCustomization.messages.reloadRequired', 'Reload the page to see some changes.'),
        });
        if (!settings.i18nEnabled) {
          localStorage.setItem('i18n-disabled', 'true');
        } else {
          localStorage.removeItem('i18n-disabled');
        }
        // Refresh public UI customization store so branding (title + favicon)
        // updates in the current session without requiring a hard reload.
        refreshBranding();
      } else {
        const detail = await response.json().catch(() => null);
        const message =
          (detail && typeof detail.detail === 'string' && detail.detail) ||
          t(
            'settings:uiCustomization.messages.saveError',
            'Failed to save UI customization settings',
          );
        throw new Error(message);
      }
    } catch (error) {
      toast({
        title: t('settings:uiCustomization.messages.saveError', 'Failed to save UI customization settings'),
        description: error instanceof Error ? error.message : undefined,
        variant: 'destructive',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setSettings((prev) => ({ ...prev, [name]: value }));
    if (name === 'customLogoUrl') {
      setLogoError(false);
    } else if (name === 'faviconUrl') {
      setFaviconError(false);
    }
  };

  const handleI18nToggle = (checked: boolean) => {
    setSettings((prev) => ({ ...prev, i18nEnabled: checked }));
  };

  const handleResetCss = () => {
    setSettings((prev) => ({ ...prev, customCss: '' }));
  };

  const handleResetAbout = () => {
    setSettings((prev) => ({ ...prev, aboutContent: '' }));
  };

  const handleResetLogo = () => {
    setSettings((prev) => ({ ...prev, customLogoUrl: '' }));
    setLogoError(false);
  };

  const handleResetFavicon = () => {
    setSettings((prev) => ({ ...prev, faviconUrl: '' }));
    setFaviconError(false);
  };

  const handleResetBrandingNames = () => {
    setSettings((prev) => ({ ...prev, appDisplayName: '', appShortName: '' }));
  };

  /** Validate http/https image URL. Shared between custom logo and favicon. */
  const validateImageUrl = (url: string): boolean => {
    if (!url) return true;
    try {
      const parsed = new URL(url);
      return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch {
      return false;
    }
  };
  // Keep legacy alias used by existing logo block.
  const validateLogoUrl = validateImageUrl;

  if (isLoading) {
    // Multi-section skeleton: tab strip + branding/theme/home customization cards
    return (
      <div className="space-y-6">
        <SkeletonLine height="h-10" width="w-full" className="max-w-md" />
        <CardSkeleton titleWidth="w-40" descriptionWidth="w-72" contentRows={4} />
        <CardSkeleton titleWidth="w-32" descriptionWidth="w-64" contentRows={3} />
        <CardSkeleton titleWidth="w-48" descriptionWidth="w-80" contentRows={5} />
      </div>
    );
  }

  return (
    <>
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Palette className="w-8 h-8" />
          {t('settings:uiCustomization.title', 'UI Customization')}
        </h1>
        <p className="text-muted-foreground mt-1">
          {t('settings:uiCustomization.description', 'Customize the application branding, language settings, and appearance.')}
        </p>
      </div>

      <div className="space-y-8">
        {/* Internationalization Settings */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Languages className="h-5 w-5 text-muted-foreground" />
            <h3 className="text-lg font-medium">
              {t('settings:uiCustomization.i18n.title', 'Language Settings')}
            </h3>
          </div>
          <div className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-0.5">
              <Label htmlFor="i18n-enabled" className="text-base font-medium">
                {t('settings:uiCustomization.i18n.enableLabel', 'Enable Internationalization')}
              </Label>
              <p className="text-sm text-muted-foreground">
                {t('settings:uiCustomization.i18n.enableDescription', 'When disabled, the application will always use English regardless of browser settings.')}
              </p>
            </div>
            <Switch
              id="i18n-enabled"
              checked={settings.i18nEnabled}
              onCheckedChange={handleI18nToggle}
              disabled={!hasWriteAccess}
            />
          </div>
        </div>

        <Separator />

        {/* Branding (display name + short name) */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Tag className="h-5 w-5 text-muted-foreground" />
              <h3 className="text-lg font-medium">
                {t('settings:uiCustomization.branding.title', 'Branding')}
              </h3>
            </div>
            {(settings.appDisplayName || settings.appShortName) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleResetBrandingNames}
                disabled={!hasWriteAccess}
              >
                <RotateCcw className="h-4 w-4 mr-1" />
                {t('common:actions.reset', 'Reset')}
              </Button>
            )}
          </div>
          <Alert variant="default">
            <AlertDescription>
              {t(
                'settings:uiCustomization.branding.help',
                'The display name overrides the product name in welcome/about/copilot copy and in the browser tab title. The PWA manifest name and the static page title set at build time are not updated by these settings.',
              )}
            </AlertDescription>
          </Alert>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="appDisplayName">
                {t('settings:uiCustomization.branding.displayNameLabel', 'Display name')}
              </Label>
              <Input
                id="appDisplayName"
                name="appDisplayName"
                value={settings.appDisplayName}
                onChange={handleChange}
                placeholder={DEFAULT_APP_NAME}
                disabled={!hasWriteAccess}
                maxLength={APP_DISPLAY_NAME_MAX_LEN}
              />
              <p className="text-sm text-muted-foreground">
                {t(
                  'settings:uiCustomization.branding.displayNameHelp',
                  'Leave empty to use the default product name ({{defaultName}}). Maximum {{max}} characters.',
                  { defaultName: DEFAULT_APP_NAME, max: APP_DISPLAY_NAME_MAX_LEN },
                )}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="appShortName">
                {t('settings:uiCustomization.branding.shortNameLabel', 'Short name (optional)')}
              </Label>
              <Input
                id="appShortName"
                name="appShortName"
                value={settings.appShortName}
                onChange={handleChange}
                placeholder={t(
                  'settings:uiCustomization.branding.shortNamePlaceholder',
                  'e.g. an acronym for compact UI',
                )}
                disabled={!hasWriteAccess}
                maxLength={APP_SHORT_NAME_MAX_LEN}
              />
              <p className="text-sm text-muted-foreground">
                {t(
                  'settings:uiCustomization.branding.shortNameHelp',
                  'Used in tight spaces (e.g. "Ask {{shortName}}"). Falls back to the display name when empty. Maximum {{max}} characters.',
                  { max: APP_SHORT_NAME_MAX_LEN, shortName: settings.appShortName || settings.appDisplayName || DEFAULT_APP_NAME },
                )}
              </p>
            </div>
          </div>
        </div>

        <Separator />

        {/* Custom Logo */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Image className="h-5 w-5 text-muted-foreground" />
              <h3 className="text-lg font-medium">
                {t('settings:uiCustomization.logo.title', 'Custom Logo')}
              </h3>
            </div>
            {settings.customLogoUrl && (
              <Button variant="ghost" size="sm" onClick={handleResetLogo} disabled={!hasWriteAccess}>
                <RotateCcw className="h-4 w-4 mr-1" />
                {t('common:actions.reset', 'Reset')}
              </Button>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="customLogoUrl">
              {t('settings:uiCustomization.logo.urlLabel', 'Logo URL')}
            </Label>
            <Input
              id="customLogoUrl"
              name="customLogoUrl"
              value={settings.customLogoUrl}
              onChange={handleChange}
              placeholder={t('settings:uiCustomization.logo.urlPlaceholder', 'https://example.com/logo.svg')}
              disabled={!hasWriteAccess}
            />
            {settings.customLogoUrl && !validateLogoUrl(settings.customLogoUrl) && (
              <p className="text-sm text-destructive">
                {t('settings:uiCustomization.logo.invalidUrl', 'Please enter a valid HTTP or HTTPS URL')}
              </p>
            )}
            <p className="text-sm text-muted-foreground">
              {t('settings:uiCustomization.logo.help', 'Enter the URL of your custom logo. Supports SVG, PNG, or JPG formats. Recommended size: 40x40 pixels.')}
            </p>
          </div>
          {settings.customLogoUrl && validateLogoUrl(settings.customLogoUrl) && (
            <div className="flex items-center gap-4 p-4 rounded-lg border bg-muted/30">
              <span className="text-sm text-muted-foreground">
                {t('settings:uiCustomization.logo.preview', 'Preview:')}
              </span>
              {logoError ? (
                <div className="flex items-center gap-2 text-destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <span className="text-sm">{t('settings:uiCustomization.logo.loadError', 'Failed to load image')}</span>
                </div>
              ) : (
                <img
                  src={settings.customLogoUrl}
                  alt="Logo preview"
                  className="h-10 w-10 object-contain"
                  onError={() => setLogoError(true)}
                />
              )}
              <a
                href={settings.customLogoUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-primary hover:underline flex items-center gap-1"
              >
                <ExternalLink className="h-3 w-3" />
                {t('settings:uiCustomization.logo.openInNewTab', 'Open in new tab')}
              </a>
            </div>
          )}
        </div>

        <Separator />

        {/* Favicon */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Image className="h-5 w-5 text-muted-foreground" />
              <h3 className="text-lg font-medium">
                {t('settings:uiCustomization.favicon.title', 'Browser Favicon')}
              </h3>
            </div>
            {settings.faviconUrl && (
              <Button variant="ghost" size="sm" onClick={handleResetFavicon} disabled={!hasWriteAccess}>
                <RotateCcw className="h-4 w-4 mr-1" />
                {t('common:actions.reset', 'Reset')}
              </Button>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="faviconUrl">
              {t('settings:uiCustomization.favicon.urlLabel', 'Favicon URL')}
            </Label>
            <Input
              id="faviconUrl"
              name="faviconUrl"
              value={settings.faviconUrl}
              onChange={handleChange}
              placeholder={t(
                'settings:uiCustomization.favicon.urlPlaceholder',
                'https://example.com/favicon.svg',
              )}
              disabled={!hasWriteAccess}
            />
            {settings.faviconUrl && !validateImageUrl(settings.faviconUrl) && (
              <p className="text-sm text-destructive">
                {t('settings:uiCustomization.favicon.invalidUrl', 'Please enter a valid HTTP or HTTPS URL')}
              </p>
            )}
            <p className="text-sm text-muted-foreground">
              {t(
                'settings:uiCustomization.favicon.help',
                'Applied at runtime to the browser tab. The static <link rel="icon"> in the shipped index.html and the PWA manifest are not updated by this setting.',
              )}
            </p>
          </div>
          {settings.faviconUrl && validateImageUrl(settings.faviconUrl) && (
            <div className="flex items-center gap-4 p-4 rounded-lg border bg-muted/30">
              <span className="text-sm text-muted-foreground">
                {t('settings:uiCustomization.favicon.preview', 'Preview:')}
              </span>
              {faviconError ? (
                <div className="flex items-center gap-2 text-destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <span className="text-sm">
                    {t('settings:uiCustomization.favicon.loadError', 'Failed to load image')}
                  </span>
                </div>
              ) : (
                <img
                  src={settings.faviconUrl}
                  alt="Favicon preview"
                  className="h-6 w-6 object-contain"
                  onError={() => setFaviconError(true)}
                />
              )}
              <a
                href={settings.faviconUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-primary hover:underline flex items-center gap-1"
              >
                <ExternalLink className="h-3 w-3" />
                {t('settings:uiCustomization.favicon.openInNewTab', 'Open in new tab')}
              </a>
            </div>
          )}
        </div>

        <Separator />

        {/* Custom About Content */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileText className="h-5 w-5 text-muted-foreground" />
              <h3 className="text-lg font-medium">
                {t('settings:uiCustomization.about.title', 'Custom About Page Content')}
              </h3>
            </div>
            {settings.aboutContent && (
              <Button variant="ghost" size="sm" onClick={handleResetAbout} disabled={!hasWriteAccess}>
                <RotateCcw className="h-4 w-4 mr-1" />
                {t('common:actions.reset', 'Reset')}
              </Button>
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            {t('settings:uiCustomization.about.description', 'Replace the default About page content with custom Markdown. Leave empty to use the default content.')}
          </p>
          <Tabs value={previewTab} onValueChange={(v) => setPreviewTab(v as 'edit' | 'preview')}>
            <TabsList>
              <TabsTrigger value="edit">
                <Code className="h-4 w-4 mr-1" />
                {t('settings:uiCustomization.about.editTab', 'Edit')}
              </TabsTrigger>
              <TabsTrigger value="preview">
                <Eye className="h-4 w-4 mr-1" />
                {t('settings:uiCustomization.about.previewTab', 'Preview')}
              </TabsTrigger>
            </TabsList>
            <TabsContent value="edit" className="mt-4">
              <Textarea
                name="aboutContent"
                value={settings.aboutContent}
                onChange={handleChange}
                placeholder={t('settings:uiCustomization.about.placeholder', '# About Our Company\n\nWrite your custom about page content here using **Markdown**...')}
                disabled={!hasWriteAccess}
                rows={12}
                className="font-mono text-sm"
              />
            </TabsContent>
            <TabsContent value="preview" className="mt-4">
              <div className="min-h-[300px] rounded-lg border p-4 bg-background">
                {settings.aboutContent ? (
                  <MarkdownViewer markdown={settings.aboutContent} />
                ) : (
                  <p className="text-muted-foreground italic">
                    {t('settings:uiCustomization.about.noContent', 'No custom content. The default About page will be shown.')}
                  </p>
                )}
              </div>
            </TabsContent>
          </Tabs>
        </div>

        <Separator />

        {/* Custom CSS */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Code className="h-5 w-5 text-muted-foreground" />
              <h3 className="text-lg font-medium">
                {t('settings:uiCustomization.css.title', 'Custom Stylesheet')}
              </h3>
            </div>
            {settings.customCss && (
              <Button variant="ghost" size="sm" onClick={handleResetCss} disabled={!hasWriteAccess}>
                <RotateCcw className="h-4 w-4 mr-1" />
                {t('common:actions.reset', 'Reset')}
              </Button>
            )}
          </div>
          <Alert variant="default">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>{t('settings:uiCustomization.css.warningTitle', 'Use with caution')}</AlertTitle>
            <AlertDescription>
              {t('settings:uiCustomization.css.warningDescription', 'Invalid or conflicting CSS may break the UI. If the application becomes unusable, clear this field to restore normal functionality. Changes require a page reload.')}
            </AlertDescription>
          </Alert>
          <div className="space-y-2">
            <Label htmlFor="customCss">
              {t('settings:uiCustomization.css.label', 'Custom CSS')}
            </Label>
            <Textarea
              id="customCss"
              name="customCss"
              value={settings.customCss}
              onChange={handleChange}
              placeholder={t('settings:uiCustomization.css.placeholder', '/* Override CSS variables */\n:root {\n  --primary: 220 70% 50%;\n}\n\n/* Custom styles */\n.my-custom-class {\n  color: red;\n}')}
              disabled={!hasWriteAccess}
              rows={10}
              className="font-mono text-sm"
            />
            <p className="text-sm text-muted-foreground">
              {t('settings:uiCustomization.css.help', 'Enter custom CSS to override the default theme. You can modify CSS variables defined in :root to change colors throughout the app.')}
            </p>
          </div>
        </div>
        {hasWriteAccess && (
          <div className="pt-4">
            <Button onClick={handleSaveSettings} disabled={isSaving}>
              {isSaving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              {t('settings:uiCustomization.saveButton', 'Save UI Settings')}
            </Button>
          </div>
        )}
      </div>
    </>
  );
}

