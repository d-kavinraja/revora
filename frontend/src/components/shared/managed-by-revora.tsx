import { Pill } from '@/components/shared/pill';
import { REVORA_MANAGEMENT_LABEL } from '@/lib/chat-state';

/**
 * Unified management-attribution badge. Single source for the `Managed by
 * Revora` label used across model selectors, model cards, provider groups,
 * kLLM service pages and Admin model-management surfaces.
 *
 * Only render for models/services that are actually integrated and managed
 * through Revora (kLLM, Revora-managed hosted models, or Revora-managed
 * provider configuration). Never render for third-party providers or
 * independently managed services.
 */
export function ManagedByRevora({
  className,
  title,
  size = 'md',
}: {
  className?: string;
  /** Optional accessible tooltip. Defaults to the attribution label. */
  title?: string;
  size?: 'xs' | 'md';
}) {
  const cls =
    size === 'xs'
      ? `px-1.5 py-0.5 text-[10px] font-medium normal-case tracking-normal ${className ?? ''}`
      : className;
  return (
    <Pill tone="brand" className={cls} title={title ?? REVORA_MANAGEMENT_LABEL}>
      {REVORA_MANAGEMENT_LABEL}
    </Pill>
  );
}
