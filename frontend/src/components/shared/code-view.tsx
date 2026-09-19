'use client';

import { useCallback, useState } from 'react';
import Editor, { loader, type OnMount } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import { Check, ChevronDown, Copy, FileCode2 } from 'lucide-react';

// Use the locally installed monaco-editor instead of the CDN default so the
// viewer works offline/self-hosted and with a pinned version.
loader.config({ monaco });

// Map common markdown fence tags to Monaco language ids.
const LANGUAGE_ALIASES: Record<string, string> = {
  js: 'javascript',
  jsx: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  py: 'python',
  sh: 'shell',
  bash: 'shell',
  zsh: 'shell',
  console: 'shell',
  yml: 'yaml',
  dockerfile: 'dockerfile',
  docker: 'dockerfile',
  cs: 'csharp',
  kt: 'kotlin',
  rs: 'rust',
  gql: 'graphql',
  patch: 'diff',
};

const SUPPORTED_LANGUAGES = new Set([
  'javascript', 'typescript', 'python', 'java', 'csharp', 'cpp', 'c', 'go',
  'rust', 'ruby', 'php', 'swift', 'kotlin', 'scala', 'shell', 'powershell',
  'json', 'yaml', 'xml', 'html', 'css', 'scss', 'less', 'sql', 'graphql',
  'markdown', 'dockerfile', 'ini', 'toml', 'diff', 'plaintext',
]);

function normalizeLanguage(raw?: string): string {
  if (!raw) return 'plaintext';
  const lang = (LANGUAGE_ALIASES[raw.toLowerCase()] ?? raw.toLowerCase()).trim();
  return SUPPORTED_LANGUAGES.has(lang) ? lang : 'plaintext';
}

interface CodeViewProps {
  code: string;
  language?: string;
  /** File path / block title shown in the header bar. */
  title?: string;
  /** Collapse long blocks by default; user can expand. */
  collapsible?: boolean;
  /** Maximum editor height in px before internal scrolling kicks in. */
  maxHeight?: number;
}

const LINE_HEIGHT = 19;
const MAX_HEIGHT_DEFAULT = 480;
const COLLAPSED_HEIGHT = 220;

/**
 * Always-light, GitHub-style read-only code viewer.
 *
 * The Revora portal may be in dark mode, but this component intentionally
 * renders white in every theme: Monaco is pinned to its built-in `light`
 * theme (independent of the app's `.dark` class) and every surrounding
 * style uses hardcoded light hex values instead of theme tokens, so global
 * dark-mode selectors cannot restyle it.
 */
export function CodeView({
  code,
  language,
  title,
  collapsible = true,
  maxHeight = MAX_HEIGHT_DEFAULT,
}: CodeViewProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [copied, setCopied] = useState(false);
  const [height, setHeight] = useState(() =>
    Math.min(Math.max(code.split('\n').length * LINE_HEIGHT + 24, 64), maxHeight),
  );

  const normalizedLanguage = normalizeLanguage(language);

  const handleMount: OnMount = useCallback(
    (editor) => {
      editor.onDidContentSizeChange((e) => {
        setHeight(Math.min(Math.max(e.contentHeight + 16, 64), maxHeight));
      });
    },
    [maxHeight],
  );

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      // Clipboard API unavailable (permissions/insecure context) — legacy fallback.
      const ta = document.createElement('textarea');
      ta.value = code;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }, [code]);

  const visibleHeight = collapsed ? Math.min(height, COLLAPSED_HEIGHT) : height;

  return (
    <div
      className="overflow-hidden rounded-xl border border-[#d0d7de] bg-white"
      style={{ colorScheme: 'light' }}
      data-code-view="light"
    >
      {/* Header bar — GitHub file-header style */}
      <div className="flex items-center gap-2 border-b border-[#d0d7de] bg-[#f6f8fa] px-3 py-2">
        <FileCode2 size={14} className="shrink-0 text-[#57606a]" />
        <span className="min-w-0 flex-1 truncate font-mono text-xs font-medium text-[#24292f]">
          {title ?? (normalizedLanguage === 'plaintext' ? 'code' : normalizedLanguage)}
        </span>
        {normalizedLanguage !== 'plaintext' && (
          <span className="hidden rounded-full border border-[#d0d7de] bg-white px-2 py-0.5 font-mono text-[10px] text-[#57606a] sm:inline">
            {normalizedLanguage}
          </span>
        )}
        {collapsible && (
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-[#57606a] transition-colors hover:bg-[#eaeef2] hover:text-[#24292f]"
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand code block' : 'Collapse code block'}
          >
            <ChevronDown
              size={14}
              className={`transition-transform ${collapsed ? '-rotate-90' : ''}`}
            />
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
        )}
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-[#57606a] transition-colors hover:bg-[#eaeef2] hover:text-[#24292f]"
          aria-label="Copy code to clipboard"
        >
          {copied ? <Check size={14} className="text-[#1a7f37]" /> : <Copy size={14} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>

      {/* Editor — Monaco pinned to its built-in light theme */}
      <div style={{ height: visibleHeight }} className="relative bg-white">
        <Editor
          height={visibleHeight}
          language={normalizedLanguage}
          value={code}
          theme="light"
          loading={
            <div className="flex h-full items-center px-4 font-mono text-xs text-[#57606a]">
              Loading code viewer…
            </div>
          }
          onMount={handleMount}
          options={{
            readOnly: true,
            domReadOnly: true,
            renderValidationDecorations: 'off',
            minimap: { enabled: false },
            lineNumbers: 'on',
            glyphMargin: false,
            folding: true,
            lineDecorationsWidth: 8,
            lineNumbersMinChars: 3,
            renderLineHighlight: 'none',
            stickyScroll: { enabled: false },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            fontSize: 13,
            lineHeight: LINE_HEIGHT,
            fontFamily:
              'ui-monospace,SFMono-Regular,SF Mono,Menlo,Consolas,Liberation Mono,monospace',
            padding: { top: 8, bottom: 8 },
            scrollbar: {
              verticalScrollbarSize: 10,
              horizontalScrollbarSize: 10,
              useShadows: false,
            },
            wordWrap: 'off',
            quickSuggestions: false,
            suggestOnTriggerCharacters: false,
            hover: { enabled: true },
            links: false,
            contextmenu: false,
            selectionHighlight: true,
            occurrencesHighlight: 'off',
            hideCursorInOverviewRuler: true,
            overviewRulerBorder: false,
            renderWhitespace: 'none',
          }}
        />
      </div>
    </div>
  );
}
