// Type declaration to fix react-syntax-highlighter compatibility with React 18
declare module 'react-syntax-highlighter' {
  import { ComponentType } from 'react';
  
  export interface SyntaxHighlighterProps {
    children?: string;
    language?: string;
    style?: { [key: string]: React.CSSProperties };
    showLineNumbers?: boolean;
    startingLineNumber?: number;
    lineNumberStyle?: React.CSSProperties | ((lineNumber: number) => React.CSSProperties);
    wrapLines?: boolean;
    wrapLongLines?: boolean;
    lineProps?: ((lineNumber: number) => React.HTMLProps<HTMLElement>) | React.HTMLProps<HTMLElement>;
    customStyle?: React.CSSProperties;
    codeTagProps?: React.HTMLProps<HTMLElement>;
    useInlineStyles?: boolean;
    PreTag?: string | ComponentType<any>;
    CodeTag?: string | ComponentType<any>;
    [key: string]: any;
  }
  
  export const PrismAsyncLight: ComponentType<SyntaxHighlighterProps> & {
    registerLanguage: (name: string, language: any) => void;
  };
  
  export const Prism: ComponentType<SyntaxHighlighterProps> & {
    registerLanguage: (name: string, language: any) => void;
  };
  
  export const Light: ComponentType<SyntaxHighlighterProps> & {
    registerLanguage: (name: string, language: any) => void;
  };
  
  const SyntaxHighlighter: ComponentType<SyntaxHighlighterProps>;
  export default SyntaxHighlighter;
}

declare module 'react-syntax-highlighter/dist/esm/languages/prism/sql' {
  const sql: any;
  export default sql;
}

declare module 'react-syntax-highlighter/dist/esm/languages/prism/python' {
  const python: any;
  export default python;
}

declare module 'react-syntax-highlighter/dist/esm/styles/prism' {
  export const oneLight: { [key: string]: React.CSSProperties };
  export const oneDark: { [key: string]: React.CSSProperties };
  export const prism: { [key: string]: React.CSSProperties };
  export const tomorrow: { [key: string]: React.CSSProperties };
  export const vscDarkPlus: { [key: string]: React.CSSProperties };
}
