import { Github, BookOpenCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from '@/components/ui/button';
import { getLandingPageFeatures, FeatureConfig } from '@/config/features';
import { useFeatureVisibilityStore } from '@/stores/feature-visibility-store';
import { useUICustomizationStore } from '@/stores/ui-customization-store';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { format } from 'date-fns';
import MarkdownViewer from '@/components/ui/markdown-viewer';

export default function About() {
  const { t } = useTranslation(['about', 'features']);
  const allowedMaturities = useFeatureVisibilityStore((state) => state.allowedMaturities);
  const customAboutContent = useUICustomizationStore((state) => state.aboutContent);
  const [appVersion, setAppVersion] = useState<string | null>(null);
  const [serverStartTime, setServerStartTime] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchServerInfo = async () => {
      try {
        const response = await fetch('/api/version');
        if (response.ok) {
          const data = await response.json();
          setAppVersion(data.version);
          setServerStartTime(data.startTime * 1000); // Convert to milliseconds
        }
      } catch (error) {
        console.error('Failed to fetch server info:', error);
      } finally {
        setLoading(false);
      }
    };
    fetchServerInfo();
  }, []);

  const features = getLandingPageFeatures(allowedMaturities);

  // If custom about content is set, render it instead of the default
  if (customAboutContent) {
    return (
      <div className="container mx-auto px-4 py-8">
        <MarkdownViewer markdown={customAboutContent} />
        
        {/* Still show version info for transparency */}
        <div className="mt-10 p-4 border rounded-lg bg-card text-card-foreground">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-muted-foreground">{t('about:version')}</p>
              {loading ? (
                <p className="font-semibold">{t('about:loading')}</p>
              ) : appVersion ? (
                <p className="font-semibold">{appVersion}</p>
              ) : (
                <p className="font-semibold text-muted-foreground">{t('about:unavailable')}</p>
              )}
            </div>
            <div>
              <p className="text-sm text-muted-foreground">{t('about:runningSince')}</p>
              {loading ? (
                <p className="font-semibold">{t('about:loading')}</p>
              ) : serverStartTime ? (
                <p className="font-semibold">{format(new Date(serverStartTime), 'PPpp')}</p>
              ) : (
                <p className="font-semibold text-muted-foreground">{t('about:unavailable')}</p>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-4xl font-bold mb-6">{t('about:title')}</h1>
      <p className="text-lg text-muted-foreground mb-6">{t('about:intro')}</p>
      
      {/* Version and Runtime Info */}
      <div className="mb-10 p-4 border rounded-lg bg-card text-card-foreground">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <p className="text-sm text-muted-foreground">{t('about:version')}</p>
            {loading ? (
              <p className="font-semibold">{t('about:loading')}</p>
            ) : appVersion ? (
              <p className="font-semibold">{appVersion}</p>
            ) : (
              <p className="font-semibold text-muted-foreground">{t('about:unavailable')}</p>
            )}
          </div>
          <div>
            <p className="text-sm text-muted-foreground">{t('about:runningSince')}</p>
            {loading ? (
              <p className="font-semibold">{t('about:loading')}</p>
            ) : serverStartTime ? (
              <p className="font-semibold">{format(new Date(serverStartTime), 'PPpp')}</p>
            ) : (
              <p className="font-semibold text-muted-foreground">{t('about:unavailable')}</p>
            )}
          </div>
        </div>
      </div>

      <h2 className="text-3xl font-semibold mb-8">{t('about:coreFeatures')}</h2>

      {features.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-12">
          {features.map((feature: FeatureConfig) => (
            <Card key={feature.id} className="flex flex-col relative">
              {feature.maturity !== 'ga' && (
                <span className={cn(
                  "absolute top-2 right-2 text-xs font-semibold px-2 py-0.5 rounded-full z-10",
                  feature.maturity === 'beta' ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300" : "",
                  feature.maturity === 'alpha' ? "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300" : ""
                )}>
                  {feature.maturity.toUpperCase()}
                </span>
              )}
              <CardHeader>
                <div className="flex items-center gap-3 mb-2">
                  <feature.icon className="w-6 h-6 text-primary" />
                  <CardTitle>{t(`features:${feature.id}.name`, { defaultValue: feature.name })}</CardTitle>
                </div>
                <CardDescription>{t(`features:${feature.id}.description`, { defaultValue: feature.description })}</CardDescription>
              </CardHeader>
              <CardContent className="flex-grow">
                {(() => {
                  const points = t(`about:details.${feature.id}`, { returnObjects: true }) as unknown as string[] | undefined;
                  return Array.isArray(points) && points.length > 0 ? (
                    <ul className="space-y-1.5 text-sm text-muted-foreground mt-2">
                      {points.map((point, index) => (
                        <li key={index}>{point}</li>
                      ))}
                    </ul>
                  ) : null;
                })()}
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <p className="text-muted-foreground text-center mb-12">{t('about:noFeatures')}</p>
      )}

      <h2 className="text-3xl font-semibold mb-6">{t('about:techStack')}</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-12 text-center">
        <div className="p-4 border rounded-lg bg-card text-card-foreground">
          <p className="font-semibold">{t('about:stack.frontend.title')}</p>
          <p className="text-sm text-muted-foreground">{t('about:stack.frontend.desc')}</p>
        </div>
        <div className="p-4 border rounded-lg bg-card text-card-foreground">
          <p className="font-semibold">{t('about:stack.backend.title')}</p>
          <p className="text-sm text-muted-foreground">{t('about:stack.backend.desc')}</p>
        </div>
        <div className="p-4 border rounded-lg bg-card text-card-foreground">
          <p className="font-semibold">{t('about:stack.database.title')}</p>
          <p className="text-sm text-muted-foreground">{t('about:stack.database.desc')}</p>
        </div>
        <div className="p-4 border rounded-lg bg-card text-card-foreground">
          <p className="font-semibold">{t('about:stack.platform.title')}</p>
          <p className="text-sm text-muted-foreground">{t('about:stack.platform.desc')}</p>
        </div>
      </div>

      <h2 className="text-3xl font-semibold mb-6">{t('about:learnMore')}</h2>
      <div className="flex flex-col md:flex-row gap-4">
        <Button asChild size="lg">
          <a href="https://github.com/larsgeorge/ontos" target="_blank" rel="noopener noreferrer">
            <Github className="mr-2 h-5 w-5" /> {t('about:cta.github')}
          </a>
        </Button>
        <Button variant="outline" asChild size="lg">
          <Link to="/user-guide">
            <BookOpenCheck className="mr-2 h-5 w-5" /> {t('about:cta.docs')}
          </Link>
        </Button>
      </div>
    </div>
  );
} 