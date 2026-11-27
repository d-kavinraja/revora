'use client';

import { cloneElement, isValidElement, type ReactElement, type ReactNode } from 'react';

type Tag = 'h1' | 'h2' | 'h3' | 'p' | 'span';

/**
 * Splits static text into per-word `<span class="w">` targets for GSAP word
 * reveals, recursing into <em>/<span> children and keeping <br> intact.
 *
 * Splitting happens at render time (server and client) so the SSR HTML already
 * contains the word spans: no hydration mismatch, no layout shift, and real
 * text stays in the markup for SEO.
 */
function splitNode(node: ReactNode, key: string): ReactNode {
  if (typeof node === 'string') {
    return node
      .split(/(\s+)/)
      .filter((part) => part.length > 0)
      .map((part, i) =>
        /^\s+$/.test(part) ? (
          ' '
        ) : (
          <span className="w" key={`${key}-${i}`}>
            {part}
          </span>
        ),
      );
  }

  if (typeof node === 'number') {
    return (
      <span className="w" key={key}>
        {String(node)}
      </span>
    );
  }

  if (Array.isArray(node)) {
    return node.map((child, i) => splitNode(child, `${key}-${i}`));
  }

  if (isValidElement(node)) {
    const element = node as ReactElement<{ children?: ReactNode }>;
    if (element.type === 'br') return <br key={key} />;
    const inner = splitNode(element.props.children, `${key}c`);
    return cloneElement(element, { key }, inner);
  }

  return node;
}

export function Split({
  as: Tag = 'h2',
  className,
  children,
  ...rest
}: {
  as?: Tag;
  className?: string;
  children: ReactNode;
} & Omit<React.HTMLAttributes<HTMLElement>, 'children'>) {
  const Component = Tag as 'h2';
  return (
    <Component className={className} {...rest}>
      {splitNode(children, 'w')}
    </Component>
  );
}
