import { Trans } from 'react-i18next';

/** HTML-escape a value for <Trans>: with `escapeValue: false` (React escapes), a raw `<` in a name
 *  would be parsed as markup; `shouldUnescape` turns the entities back into text after parsing. */
const escapeForTrans = (value: string) => value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

interface RuleSentenceProps {
  kind: string;
  assignee: string;
  action: string;
  target?: string | null;
}

/** One translated sentence per rule kind, so each language orders who / action / target itself. */
export default function RuleSentence({ kind, assignee, action, target }: RuleSentenceProps) {
  return (
    <Trans
      i18nKey={`access-policies:details.ruleSentence.${kind}${target ? '' : 'NoTarget'}`}
      values={{ assignee: escapeForTrans(assignee), action: escapeForTrans(action), target: escapeForTrans(target || '') }}
      shouldUnescape
      components={{ who: <strong />, act: <strong />, tgt: <code className="rounded bg-muted px-1" /> }}
    />
  );
}
