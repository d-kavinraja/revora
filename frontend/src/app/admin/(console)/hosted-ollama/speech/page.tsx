'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AudioLinesIcon } from 'lucide-react';
import {
  adminApi,
  type AdminSpeechStatus,
  type AdminSpeechUpdate,
} from '@/lib/api';
import { apiErrorMessage, isApiTransportError } from '@/lib/api-transport';
import { AdminPage, AdminSection } from '@/components/admin/page-shell';
import { StatusRibbon } from '@/components/admin/metrics';
import {
  AdminButton,
  AdminSwitch,
  ADMIN_INPUT_CLASS,
  Field,
} from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';
import { useToast } from '@/components/ui/toaster';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { HostedTabs } from '../hosted-tabs';

const REFRESH_INTERVAL_MS = 15_000;

function errorMessage(err: unknown): string {
  return apiErrorMessage(err) ?? 'Something went wrong. Please try again.';
}

interface SpeechFormProps {
  data: AdminSpeechStatus;
  saving: boolean;
  onSave: (update: AdminSpeechUpdate) => void;
}

function SpeechForm({ data, saving, onSave }: SpeechFormProps) {
  const [enabled, setEnabled] = useState(data.enabled);
  const [maxRecording, setMaxRecording] = useState(data.max_recording_seconds);
  const [maxAudio, setMaxAudio] = useState(data.max_audio_mb);
  const [queueTimeout, setQueueTimeout] = useState(data.queue_timeout_s);

  const recordingValid = Number.isInteger(maxRecording) && maxRecording >= 5 && maxRecording <= 60;
  const audioValid = Number.isInteger(maxAudio) && maxAudio >= 1 && maxAudio <= 5;
  const queueValid = Number.isInteger(queueTimeout) && queueTimeout >= 5 && queueTimeout <= 60;
  const valid = recordingValid && audioValid && queueValid;
  const dirty =
    enabled !== data.enabled ||
    maxRecording !== data.max_recording_seconds ||
    maxAudio !== data.max_audio_mb ||
    queueTimeout !== data.queue_timeout_s;
  const canEnable = data.environment_enabled && data.service.configured;
  const switchDisabled = saving || (!enabled && !canEnable);

  return (
    <>
      <AdminSection
        title="Policy"
        subtitle={`Applied by the backend on every request. Policy version ${data.version}.`}
        actions={
          <AdminButton
            onClick={() =>
              onSave({
                enabled,
                max_recording_seconds: maxRecording,
                max_audio_mb: maxAudio,
                queue_timeout_s: queueTimeout,
                version: data.version,
              })
            }
            disabled={!dirty || !valid || saving}
            variant="primary"
            size="sm"
          >
            {saving ? <LoaderIcon size={14} className="animate-spin" /> : null}
            Save changes
          </AdminButton>
        }
      >
        <AdminSwitch
          checked={enabled}
          onChange={setEnabled}
          disabled={switchDisabled}
          title="Enable voice input"
          description={
            canEnable
              ? 'When off, the microphone control is hidden in Chat and the backend rejects transcription requests.'
              : !data.environment_enabled
                ? 'The backend environment switch (REVORA_SPEECH_ENABLED) is off. Speech cannot be enabled here.'
                : 'The private speech service is not configured. Set its URL and service token in the backend environment before enabling.'
          }
        />
        {data.enabled && !data.service.ready ? (
          <p className="mt-3 text-xs text-warning">
            Voice input is enabled but the private service is not ready. Requests will fail closed until it is reachable.
          </p>
        ) : null}
        {data.service.error ? (
          <p className="mt-3 text-xs text-error">{data.service.error}</p>
        ) : null}

        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          <Field
            label="Maximum recording"
            htmlFor="speech-max-recording"
            hint="Seconds. Allowed 5–60; the service enforces the same ceiling."
          >
            <input
              id="speech-max-recording"
              type="number"
              min={5}
              max={60}
              value={maxRecording}
              onChange={(event) => setMaxRecording(Number(event.target.value))}
              className={ADMIN_INPUT_CLASS}
              aria-invalid={!recordingValid}
            />
          </Field>
          <Field
            label="Maximum audio size"
            htmlFor="speech-max-audio"
            hint="MiB. Allowed 1–5; larger uploads are rejected before transcription."
          >
            <input
              id="speech-max-audio"
              type="number"
              min={1}
              max={5}
              value={maxAudio}
              onChange={(event) => setMaxAudio(Number(event.target.value))}
              className={ADMIN_INPUT_CLASS}
              aria-invalid={!audioValid}
            />
          </Field>
          <Field
            label="Queue wait"
            htmlFor="speech-queue-timeout"
            hint="Seconds a request may wait for the single inference slot. Allowed 5–60."
          >
            <input
              id="speech-queue-timeout"
              type="number"
              min={5}
              max={60}
              value={queueTimeout}
              onChange={(event) => setQueueTimeout(Number(event.target.value))}
              className={ADMIN_INPUT_CLASS}
              aria-invalid={!queueValid}
            />
          </Field>
        </div>
        {!valid ? (
          <p role="alert" className="mt-3 text-xs text-error">
            Use 5–60 seconds, 1–5 MiB and a 5–60 second queue wait.
          </p>
        ) : null}
      </AdminSection>

      <AdminSection
        title="Runtime"
        subtitle="Health and queue state are read from the private service. The endpoint and tokens are never exposed here."
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">Configured</span>
            <span className="text-sm font-medium text-foreground">
              {data.service.configured ? 'Yes' : 'No'}
            </span>
          </div>
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">Reachable</span>
            <span className="text-sm font-medium text-foreground">
              {data.service.reachable ? 'Yes' : 'No'}
            </span>
          </div>
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">Ready</span>
            <span className="text-sm font-medium text-foreground">
              {data.service.ready ? 'Yes' : 'No'}
            </span>
          </div>
          <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="block text-xs text-muted-foreground">Engine</span>
            <span className="text-sm font-medium text-foreground">
              {data.engine.model} · {data.engine.compute_type} · {data.engine.language}
            </span>
          </div>
        </div>
      </AdminSection>

      <p className="px-1 text-xs leading-relaxed text-muted-foreground">
        Audio and transcripts are never written to Revora&apos;s database, Redis, disk, logs, telemetry or analytics. This page stores policy only; the transcript is inserted into the composer and is never sent automatically.
      </p>
    </>
  );
}

export default function AdminSpeechPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['admin', 'hosted-ollama', 'speech'],
    queryFn: ({ signal }) => adminApi.hostedSpeech(signal),
    refetchInterval: REFRESH_INTERVAL_MS,
    retry: false,
  });

  const update = useMutation({
    mutationFn: (payload: AdminSpeechUpdate) => adminApi.updateHostedSpeech(payload),
    onSuccess: (next) => {
      queryClient.setQueryData(['admin', 'hosted-ollama', 'speech'], next);
      toast({ title: 'Speech policy saved', type: 'success' });
    },
    onError: (err) => {
      const conflict = (err as { response?: { status?: number } })?.response?.status === 409;
      if (conflict) {
        void queryClient.invalidateQueries({ queryKey: ['admin', 'hosted-ollama', 'speech'] });
      }
      toast({
        title: conflict
          ? 'Policy changed elsewhere'
          : isApiTransportError(err)
            ? 'Cannot reach the backend'
            : 'Save failed',
        description: conflict
          ? 'The latest policy was reloaded. Review it and save again.'
          : errorMessage(err),
        type: 'error',
      });
    },
  });

  const page = (body: React.ReactNode) => (
    <AdminPage
      eyebrow="System"
      icon={<AudioLinesIcon size={28} />}
      title="Speech"
      description="Private, read-only English transcription for the Chat composer. Audio is processed in memory and discarded; the transcript is editable and is never sent automatically."
    >
      <HostedTabs />
      {body}
    </AdminPage>
  );

  if (isPending) {
    return page(
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderIcon size={22} className="text-brand" animate />
      </div>,
    );
  }

  if (isError || !data) {
    return page(<QueryError message={errorMessage(error)} onRetry={() => void refetch()} />);
  }

  const verdict = !data.environment_enabled
    ? 'Environment disabled'
    : !data.enabled
      ? 'Disabled'
      : data.service.ready
        ? 'Live'
        : 'Enabled · service unavailable';

  return page(
    <>
      <StatusRibbon
        label="Speech state"
        verdict={verdict}
        hint={
          !data.environment_enabled
            ? 'The backend environment switch is off; speech is rejected regardless of this policy.'
            : data.enabled
              ? 'Users can record a short message; one inference runs globally at a time.'
              : 'Voice input is hidden in Chat and rejected by the backend.'
        }
        readouts={[
          { key: 'active', label: 'Active', value: String(data.service.active) },
          {
            key: 'queue',
            label: 'Queue',
            value: `${data.service.queued} / ${data.service.capacity}`,
          },
          {
            key: 'inference',
            label: 'Inference cap',
            value: String(data.engine.max_concurrent_inferences),
          },
          { key: 'engine', label: 'Engine', value: data.engine.model },
        ]}
      />
      <SpeechForm
        key={data.version}
        data={data}
        saving={update.isPending}
        onSave={(payload) => update.mutate(payload)}
      />
    </>,
  );
}
