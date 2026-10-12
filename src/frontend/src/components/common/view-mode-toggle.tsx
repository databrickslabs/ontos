import React from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from "@/components/ui/button";
import { TableIcon as DefaultTableIcon } from 'lucide-react';

interface ViewModeToggleProps {
  currentView: 'table' | 'graph';
  onViewChange: (view: 'table' | 'graph') => void;
  tableViewIcon?: React.ReactNode;
  graphViewIcon: React.ReactNode; // graph icon is specific per feature, so required
  baseButtonClassName?: string;
  className?: string;
}

export const ViewModeToggle: React.FC<ViewModeToggleProps> = ({
  currentView,
  onViewChange,
  tableViewIcon,
  graphViewIcon,
  baseButtonClassName = "h-8 px-2", // Default from original views
  className = '',
}) => {
  const { t } = useTranslation('common');
  const TableIconToUse = tableViewIcon || <DefaultTableIcon className="h-4 w-4" />;

  return (
    <div className={`flex items-center gap-1 border rounded-md p-0.5 ${className}`}>
      <Button
        variant={currentView === 'table' ? 'secondary' : 'ghost'}
        size="sm"
        onClick={() => onViewChange('table')}
        className={baseButtonClassName}
        title={t('common:viewMode.tableView')}
      >
        {TableIconToUse}
      </Button>
      <Button
        variant={currentView === 'graph' ? 'secondary' : 'ghost'}
        size="sm"
        onClick={() => onViewChange('graph')}
        className={baseButtonClassName}
        title={t('common:viewMode.graphView')}
      >
        {graphViewIcon}
      </Button>
    </div>
  );
}; 