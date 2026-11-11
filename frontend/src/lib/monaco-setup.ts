'use client';

import { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';

type MonacoEnvironmentShape = Record<string, unknown> & {
  getWorker: (moduleId: string, label: string) => Worker;
};

/**
 * Self-hosted Monaco workers for the Turbopack/Next bundler.
 *
 * Monaco 0.57's bundled worker bootstrap creates a Blob module and passes it
 * the raw `/_next/static/media/editorWebWorkerMain.<hash>.js` asset path. A
 * Blob module cannot resolve that absolute-path specifier, which produces:
 *   "Failed to resolve module specifier /_next/static/media/editorWebWorkerMain..."
 *
 * Supplying real `Worker` instances through `MonacoEnvironment.getWorker`
 * lets Next/Turbopack emit each worker as its own asset and gives Monaco a
 * browser-resolvable URL, avoiding the Blob bootstrap entirely.
 */
function installMonacoEnvironment(): void {
  if (typeof window === 'undefined') return;
  const globalWithMonaco = globalThis as typeof globalThis & {
    MonacoEnvironment?: Partial<MonacoEnvironmentShape>;
  };

  globalWithMonaco.MonacoEnvironment = {
    ...(globalWithMonaco.MonacoEnvironment ?? {}),
    getWorker(_moduleId: string, label: string): Worker {
      if (label === 'json') {
        return new Worker(
          new URL(
            'monaco-editor/language/json/json.worker.js',
            import.meta.url,
          ),
          { type: 'module', name: label },
        );
      }
      if (label === 'css' || label === 'scss' || label === 'less') {
        return new Worker(
          new URL(
            'monaco-editor/language/css/css.worker.js',
            import.meta.url,
          ),
          { type: 'module', name: label },
        );
      }
      if (label === 'html' || label === 'handlebars' || label === 'razor') {
        return new Worker(
          new URL(
            'monaco-editor/language/html/html.worker.js',
            import.meta.url,
          ),
          { type: 'module', name: label },
        );
      }
      if (label === 'typescript' || label === 'javascript') {
        return new Worker(
          new URL(
            'monaco-editor/language/typescript/ts.worker.js',
            import.meta.url,
          ),
          { type: 'module', name: label },
        );
      }
      return new Worker(
        new URL(
          'monaco-editor/editor/editor.worker.js',
          import.meta.url,
        ),
        { type: 'module', name: label },
      );
    },
  };
}

installMonacoEnvironment();
loader.config({ monaco });
