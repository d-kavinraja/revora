/**
 * UI integrity regression guards.
 *
 * These tests pin the remediation of the Frontend Integrity Audit findings
 * (F-01…F-05): no fake success, no fabricated zeros, honest scope claims,
 * explicit error states, and accessible toast semantics. They assert against
 * source because the test harness is node:test without a DOM renderer.
 */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const read = (relativePath) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8');

const footer = read('../components/ui/footer.tsx');
const dashboard = read('../app/(dashboard)/dashboard/page.tsx');
const toaster = read('../components/ui/toaster.tsx');
const reviews = read('../app/(dashboard)/reviews/page.tsx');
const profile = read('../app/(dashboard)/profile/page.tsx');
const analytics = read('../app/(dashboard)/settings/analytics/page.tsx');
const mouthmap = read('../app/(dashboard)/model-lab/mouthmap/page.tsx');
const chatState = read('./chat-state.ts');
const messageBubble = read('../app/(dashboard)/chat/_components/message-bubble.tsx');
const modelPicker = read('../app/(dashboard)/chat/_components/model-picker.tsx');
const chatShell = read('../app/(dashboard)/chat/_components/chat-shell.tsx');
const chatPage = read('../app/(dashboard)/chat/page.tsx');
const persistentChatShell = read('../app/(dashboard)/chat/_components/persistent-chat-shell.tsx');
const chatContextUsage = read('../app/(dashboard)/chat/_components/chat-context-usage.tsx');
const chatTopBar = read('../app/(dashboard)/chat/_components/chat-top-bar.tsx');
const chatProviderStatusBanners = read('../app/(dashboard)/chat/_components/chat-provider-status-banners.tsx');
const rootLayout = read('../app/layout.tsx');
const providers = read('../app/providers.tsx');
const chatStore = read('../store/useChatStore.ts');
const themeStore = read('../store/useThemeStore.ts');
const adminThemeStore = read('../store/useAdminThemeStore.ts');
const authStore = read('../store/useAuthStore.ts');
const modelIcon = read('../components/ui/model-icon.tsx');
const adminHosted = read('../app/admin/(console)/hosted-ollama/page.tsx');
const adminKllm = read('../app/admin/(console)/kllm/page.tsx');
const adminModels = read('../app/admin/(console)/models/page.tsx');
const settingsKllm = read('../app/(dashboard)/settings/kllm/page.tsx');

// ─── F-01: fake newsletter subscription removed ───────────────────────────────

test('footer has no newsletter subscription feature', () => {
  assert.doesNotMatch(footer, /onSubscribe/i);
  assert.doesNotMatch(footer, /newsletter/i);
  assert.doesNotMatch(footer, /Subscrib/i);
});

test('footer has no randomized or simulated subscription success', () => {
  assert.doesNotMatch(footer, /Math\.random/);
  assert.doesNotMatch(footer, /Subscribed\. Check your inbox/);
  assert.doesNotMatch(footer, /console\.log\(`Subscribing/);
  assert.doesNotMatch(footer, /setTimeout\(resolve/);
});

test('footer navigation and branding remain', () => {
  assert.match(footer, /usefulLinks\.map/);
  assert.match(footer, /socialLinks\.map/);
  assert.match(footer, /All rights reserved/);
  assert.match(footer, /export const Footer/);
});

// ─── F-02: failed stats are never shown as zero ──────────────────────────────

test('dashboard metric fallbacks are honest, not zero', () => {
  assert.match(dashboard, /metricDisplay\(stats\?\.connected_repos\)/);
  assert.match(dashboard, /metricDisplay\(stats\?\.total_prs_reviewed\)/);
  assert.match(dashboard, /metricDisplay\(stats\?\.total_completed_reviews\)/);
  assert.doesNotMatch(dashboard, /stats\?\.\w+ \?\? 0/);
});

test('dashboard issues-caught value is unknown, not zero, without stats', () => {
  const match = dashboard.match(
    /const issuesCaughtValue = !stats\s*\?\s*'—'/,
  );
  assert.ok(match, 'issuesCaughtValue must fall back to "—" when stats are unavailable');
});

test('severity rail only renders from genuine stats and stays wired', () => {
  assert.match(dashboard, /issues_caught_available && \(\s*<SeverityRail/);
  assert.match(dashboard, /critical: stats\.critical_count/);
  assert.match(dashboard, /suggestions: stats\.suggestions_count/);
});

// ─── F-03: accessible toast announcements ────────────────────────────────────

test('toaster exposes polite and assertive live regions', () => {
  assert.match(toaster, /role="alert" aria-live="assertive"/);
  assert.match(toaster, /role="status" aria-live="polite"/);
});

test('toaster uses exactly two sibling live regions (no nested duplicates)', () => {
  const liveRegions = toaster.match(/aria-live=/g) ?? [];
  assert.equal(liveRegions.length, 2);
});

test('toaster dismiss control has an accessible name', () => {
  assert.match(toaster, /aria-label="Dismiss notification"/);
});

test('toaster keeps error and non-error toasts in separate regions', () => {
  assert.match(toaster, /t\.type === 'error'\)\.map\(toastView\)/);
  assert.match(toaster, /t\.type !== 'error'\)\.map\(toastView\)/);
});

// ─── F-04: reviews page scope claim matches the fetch ────────────────────────

test('reviews page does not claim to show all reviews', () => {
  assert.doesNotMatch(reviews, /All AI code reviews/);
  assert.match(reviews, /up to 100 shown/);
});

// ─── F-05: profile API failures are not rendered as empty ────────────────────

test('profile does not convert provider/api-key failures into empty data', () => {
  assert.doesNotMatch(profile, /catch\(\(\) => \[\]\)/);
  assert.doesNotMatch(profile, /catch\(\(\) => \[\] as/);
});

test('profile surfaces a load error with a retry action', () => {
  assert.match(profile, /setLoadError\(true\)/);
  assert.match(profile, /<ErrorBanner/);
  assert.match(profile, /Retry/);
  assert.match(profile, /void fetchData\(\)/);
});

test('profile empty state is only shown when loading succeeded', () => {
  assert.match(profile, /loadError \? \(/);
  assert.match(profile, /<ConnectedProviders providers=\{activeProviders\} loading=\{loading\} \/>/);
});

// ─── Phase 6 sweep: same-class issues fixed nearby ───────────────────────────

test('analytics error metrics are unknown, not zero, without data', () => {
  assert.doesNotMatch(analytics, /total_errors \?\? 0/);
  assert.doesNotMatch(analytics, /error_rate \?\? 0/);
  assert.match(analytics, /totalErrors !== undefined \? totalErrors\.toLocaleString\(\) : '—'/);
  assert.match(analytics, /requestsLoaded \? totalRequests\.toLocaleString\(\) : '—'/);
});

test('model lab partial load failures are surfaced, not shown as empty', () => {
  assert.match(mouthmap, /let degraded = false/);
  assert.match(mouthmap, /Some Model Lab data could not be loaded/);
});

test('no fake subscription success remains anywhere in the tested surfaces', () => {
  for (const source of [footer, dashboard, toaster, reviews, profile, analytics, mouthmap]) {
    assert.doesNotMatch(source, /Subscribed\. Check your inbox/);
  }
});

// ─── Model icon identity: every surface carries provider provenance ───────────

test('assistant response header builds its icon identity from full provenance', () => {
  assert.match(messageBubble, /responseModelIdentity\(message, metrics\?\.model\)/);
  assert.match(messageBubble, /modelIdentity=\{responseModel\}/);
  assert.doesNotMatch(messageBubble, /\{\s*key:\s*metrics\.model\s*\}/);
});

test('no ModelIcon call site passes a bare key-only identity', () => {
  const sources = [
    messageBubble,
    modelPicker,
    adminHosted,
    adminKllm,
    adminModels,
    settingsKllm,
  ];
  for (const source of sources) {
    assert.doesNotMatch(source, /<ModelIcon\s+model=\{\{\s*key:\s*[^,}\n]+\s*\}\}/);
  }
});

test('admin and settings model tables pass explicit provider provenance', () => {
  assert.match(adminHosted, /provider: HOSTED_PROVIDER/);
  assert.match(adminHosted, /category: 'hosted'/);
  assert.match(adminKllm, /provider: KLLM_PROVIDER/);
  assert.match(adminModels, /provider: override\.provider_slug/);
  assert.equal((settingsKllm.match(/provider: KLLM_PROVIDER/g) ?? []).length, 2);
  assert.match(modelPicker, /resolveSelectedModel\(models, value\)/);
  assert.match(chatState, /export function resolveSelectedModel/);
});

test('unknown-family models keep the real provider brand, not kLLM', () => {
  assert.match(chatState, /if \(provider && provider !== KLLM_PROVIDER\) return provider/);
  assert.match(chatState, /provider === 'hosted_ollama'/);
});

test('the chat header and composer share stale-key identity resolution', () => {
  assert.match(chatShell, /resolveSelectedModel\(statusQuery\.data\?\.models, activeChat\?\.model\)/);
  assert.match(modelPicker, /resolveSelectedModel\(models, value\)/);
});

test('chat requests send a canonical key while attribution keeps the requested key', () => {
  assert.match(chatShell, /model: canonicalModelKey\(chat\.model\)/);
  assert.match(chatShell, /model: chat\.model/); // stored provenance on the turn
  assert.match(chatState, /export function canonicalModelKey/);
});

test('editing the final answer does not warn about a removed later turn', () => {
  assert.match(chatShell, /if \(plan\.laterTurnCount > 0\)/);
  assert.match(chatShell, /editPrompt\(pendingEdit\.plan\.laterTurnCount\)/);
  assert.match(chatState, /const replacedAnswer = replaced\[0\]\?\.role === 'assistant'/);
});

test('edit undo snapshots and restores response telemetry', () => {
  assert.match(chatShell, /metrics: metricsSnapshot/);
  assert.match(chatShell, /return \{ \.\.\.next, \.\.\.undo\.metrics \}/);
});

test('touch devices keep message actions visible with larger targets', () => {
  assert.match(messageBubble, /\[@media\(hover:none\)\]:opacity-100/);
  assert.match(messageBubble, /\[@media\(hover:none\)\]:h-10/);
  assert.match(messageBubble, /\[@media\(hover:none\)\]:min-w-10/);
});

test('SmolLM uses the Hugging Face family icon everywhere', () => {
  assert.match(chatState, /'huggingface'/);
  assert.match(chatState, /smollm/);
  assert.match(modelIcon, /HuggingFace\.Color/);
});

// Hydration safety: the server and the first client render start from the same
// defaults. Browser-only storage is replayed after mount, never during render.
test('the root layout does not mutate the document before hydration', () => {
  assert.doesNotMatch(rootLayout, /suppressHydrationWarning/);
  assert.doesNotMatch(rootLayout, /localStorage\.getItem/);
  assert.doesNotMatch(rootLayout, /window\.matchMedia/);
  assert.match(rootLayout, /<html lang="en">/);
});

test('browser-persisted stores skip synchronous rehydration', () => {
  assert.match(themeStore, /skipHydration: true/);
  assert.match(adminThemeStore, /skipHydration: true/);
  assert.match(authStore, /skipHydration: true/);
  assert.match(providers, /persist\.rehydrate\(\)/);
  assert.match(providers, /setPreferencesHydrated\(true\)/);
  assert.match(providers, /return restoreSession\(\)/);
});

test('temporary chat ids are created after mount, not during module init', () => {
  assert.match(chatStore, /\.\.\.createEmptyChatState\(\)/);
  assert.match(chatShell, /if \(!activeId\) ensureActiveChat\(\)/);
});

test('the chat page gates query-dependent markup until after mount', () => {
  assert.match(chatPage, /useSyncExternalStore\(subscribeMounted, getClientMounted, getServerMounted\)/);
  assert.match(chatPage, /const getServerMounted = \(\) => false/);
  assert.match(chatPage, /if \(!mounted \|\| modesQuery\.isPending/);
});

// Both chat modes share the same top bar and context meter so controls stay
// anchored when toggling between Temporary and Persistent.
test('chat shells share the top bar and context meter', () => {
  assert.match(chatTopBar, /from '\.\/chat-context-usage'/);
  assert.match(chatTopBar, /<ChatContextUsage/);
  assert.match(chatTopBar, /<ModelIdentityBadge/);
  assert.match(chatTopBar, /<ChatModeSwitch/);
  assert.match(chatShell, /<ChatTopBar/);
  assert.match(persistentChatShell, /<ChatTopBar/);
  assert.match(chatContextUsage, /ContextMeter/);
});

test('persistent context is derived per conversation from shared helpers', () => {
  assert.match(persistentChatShell, /withPendingChatDraft\(base, draft\)/);
  assert.match(persistentChatShell, /nextRequestContextMeter\(contextChat/);
  assert.match(persistentChatShell, /includeIncompleteMarkers: false/);
  assert.match(persistentChatShell, /historicalTokens: lastAssistantId \? metrics\[lastAssistantId\]\?\.contextUsed/);
  assert.match(chatState, /export function withPendingChatDraft/);
  assert.match(chatState, /export function nextRequestContextMeter/);
});

// Temporary/Persistent header parity: model badge stays left of the mode switcher,
// and provider reachability banners render in persistent chat too.
test('chat top bar keeps model badge after mode switcher on the left', () => {
  const leftGroup = chatTopBar.match(
    /<div className="min-w-0 flex items-center gap-2">([\s\S]*?)<\/div>\s*<div className="flex items-center gap-1\.5">/,
  );
  assert.ok(leftGroup, 'ChatTopBar should have left and right header groups');
  const left = leftGroup[1];
  const switchIndex = left.indexOf('<ChatModeSwitch');
  const badgeIndex = left.indexOf('<ModelIdentityBadge');
  assert.ok(switchIndex >= 0, 'Left group should render ChatModeSwitch');
  assert.ok(badgeIndex >= 0, 'Left group should render ModelIdentityBadge');
  assert.ok(switchIndex < badgeIndex, 'ModelIdentityBadge should come after ChatModeSwitch in left group');
});

test('provider reachability banners are shared and rendered in persistent chat', () => {
  assert.match(chatProviderStatusBanners, /are unreachable right now\./);
  assert.match(chatProviderStatusBanners, /No AI models are available\. Ask an administrator to enable a provider\./);
  assert.match(chatShell, /<ChatProviderStatusBanners catalog=\{statusQuery\.data\} \/>/);
  assert.match(persistentChatShell, /<ChatProviderStatusBanners catalog=\{catalog\.data\} \/>/);
});

test('persistent chat reports model catalog unavailability like temporary chat', () => {
  assert.match(persistentChatShell, /onKllmStatusChange\?: \(unavailable: boolean\) => void/);
  assert.match(persistentChatShell, /onKllmStatusChange\(unavailable\)/);
  assert.match(chatPage, /<PersistentChatShell[\s\S]*onKllmStatusChange=\{setKllmUnavailable\}/);
});