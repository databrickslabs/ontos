import React from 'react';
import { withTranslation, type WithTranslation } from 'react-i18next';
import { AlertTriangle, Home, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface Props extends WithTranslation {
  children: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

class RouteErrorBoundaryInner extends React.Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[RouteErrorBoundary] Caught render error:', error, info.componentStack);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  handleGoHome = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = '/';
  };

  render() {
    const { t } = this.props;
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-6">
          <AlertTriangle className="h-12 w-12 text-destructive" />
          <h2 className="text-xl font-semibold">{t('navigation:routeError.title')}</h2>
          <p className="text-muted-foreground max-w-md">
            {t('navigation:routeError.body')}
          </p>
          {this.state.error && (
            <pre className="text-xs text-muted-foreground bg-muted rounded-md p-3 max-w-lg overflow-x-auto whitespace-pre-wrap">
              {this.state.error.message}
            </pre>
          )}
          <div className="flex gap-3 mt-2">
            <Button variant="outline" onClick={this.handleRetry}>
              <RotateCcw className="mr-2 h-4 w-4" /> {t('common:retry')}
            </Button>
            <Button onClick={this.handleGoHome}>
              <Home className="mr-2 h-4 w-4" /> {t('navigation:routeError.goHome')}
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export const RouteErrorBoundary = withTranslation(['navigation', 'common'])(
  RouteErrorBoundaryInner,
);
