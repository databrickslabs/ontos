import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
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
} from 'lucide-react';
import MarkdownViewer from '@/components/ui/markdown-viewer';

interface UICustomizationState {
  i18nEnabled: boolean;
  customLogoUrl: string;
  aboutContent: string;
  customCss: string;
}

export default function UICustomizationSettings() {
  const { t } = useTranslation(['settings', 'common']);
  const { toast } = useToast();
  const { hasPermission } = usePermissions();
  const hasWriteAccess = hasPermission('settings', FeatureAccessLevel.READ_WRITE);

  const [settings, setSettings] = useState<UICustomizationState>({
    i18nEnabled: true,
    customLogoUrl: '',
    aboutContent: '',
    customCss: '',
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [previewTab, setPreviewTab] = useState<'edit' | 'preview'>('edit');
  const [logoError, setLogoError] = useState(false);

  // Fetch settings on mount
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
        }),
      });
      if (response.ok) {
        toast({
          title: t('settings:uiCustomization.messages.saveSuccess', 'UI customization settings saved'),
          description: t('settings:uiCustomization.messages.reloadRequired', 'Reload the page to see some changes.'),
        });
        // Update localStorage for i18n setting so it takes effect on next load
        if (!settings.i18nEnabled) {
          localStorage.setItem('i18n-disabled', 'true');
        } else {
          localStorage.removeItem('i18n-disabled');
        }
      } else {
        throw new Error('Failed to save settings');
      }
    } catch (error) {
      toast({
        title: t('settings:uiCustomization.messages.saveError', 'Failed to save UI customization settings'),
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

  const validateLogoUrl = (url: string): boolean => {
    if (!url) return true;
    try {
      const parsed = new URL(url);
      return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch {
      return false;
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-10">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Palette className="h-5 w-5" />
          {t('settings:uiCustomization.title', 'UI Customization')}
        </CardTitle>
        <CardDescription>
          {t('settings:uiCustomization.description', 'Customize the application branding, language settings, and appearance.')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-8">
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
      </CardContent>
      {hasWriteAccess && (
        <CardFooter className="border-t pt-6">
          <Button onClick={handleSaveSettings} disabled={isSaving}>
            {isSaving ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            {t('settings:uiCustomization.saveButton', 'Save UI Settings')}
          </Button>
        </CardFooter>
      )}
    </Card>
  );
}

