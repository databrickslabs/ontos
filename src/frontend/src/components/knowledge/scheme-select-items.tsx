import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
} from '@/components/ui/select';
import type { SchemeOption, SchemeOptionGroup } from '@/lib/scheme-select-options';

interface SchemeSelectItemsProps {
  groups: SchemeOptionGroup[];
  /** Optional extra content shown after the muted parent text (e.g. a badge). */
  renderSuffix?: (option: SchemeOption) => React.ReactNode;
}

/**
 * Grouped scheme options for a `Select`: one labelled group per scheme type,
 * separated, with the parent scheme shown as muted text instead of indentation.
 * The parent text renders outside the item text, so the closed trigger shows
 * only the scheme label.
 */
export const SchemeSelectItems: React.FC<SchemeSelectItemsProps> = ({ groups, renderSuffix }) => {
  const { t } = useTranslation(['semantic-models']);

  const groupHeading = (type: string): string => {
    switch (type) {
      case 'glossary':
        return t('semantic-models:schemeSelect.groupGlossary', 'Glossaries');
      case 'taxonomy':
        return t('semantic-models:schemeSelect.groupTaxonomy', 'Taxonomies');
      case 'ontology':
        return t('semantic-models:schemeSelect.groupOntology', 'Ontologies');
      default:
        return type;
    }
  };

  return (
    <>
      {groups.map((group, idx) => (
        <React.Fragment key={group.type}>
          {idx > 0 && <SelectSeparator />}
          <SelectGroup>
            <SelectLabel>{groupHeading(group.type)}</SelectLabel>
            {group.options.map((opt) => {
              const suffix = renderSuffix?.(opt);
              const parentText = opt.parentLabel
                ? t('semantic-models:schemeSelect.inParent', {
                    defaultValue: 'in {{parent}}',
                    parent: opt.parentLabel,
                  })
                : null;
              const description =
                parentText || suffix ? (
                  <span className="inline-flex items-center gap-2">
                    {parentText && <span>{parentText}</span>}
                    {suffix}
                  </span>
                ) : undefined;
              return (
                <SelectItem key={opt.iri} value={opt.iri} description={description}>
                  {opt.label}
                </SelectItem>
              );
            })}
          </SelectGroup>
        </React.Fragment>
      ))}
    </>
  );
};
