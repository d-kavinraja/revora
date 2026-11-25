'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  formatSpeechError,
  isSpeechAvailabilityError,
  pickRecorderMime,
  SpeechRequestError,
  transcribeAudio,
  type SpeechPhase,
  type SpeechReadiness,
} from '@/lib/speech';

interface UseSpeechToTextOptions {
  enabled: boolean;
  disabled: boolean;
  chatId: string | null;
  maxRecordingSeconds: number;
  readiness?: SpeechReadiness;
  onTranscript: (text: string, chatId: string) => string | null;
}

export interface SpeechToTextState {
  phase: SpeechPhase;
  error: string | null;
  elapsedMs: number;
  maxSeconds: number;
  start: () => void;
  stop: () => void;
  cancel: () => void;
}

const ACTIVE_PHASES: SpeechPhase[] = [
  'requesting',
  'recording',
  'uploading',
  'queued',
  'processing',
];

export function useSpeechToText({
  enabled,
  disabled,
  chatId,
  maxRecordingSeconds,
  readiness = 'ready',
  onTranscript,
}: UseSpeechToTextOptions): SpeechToTextState {
  const [phase, setPhase] = useState<SpeechPhase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const phaseRef = useRef<SpeechPhase>('idle');
  const mountedRef = useRef(true);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recorderMimeRef = useRef<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const requestRef = useRef<AbortController | null>(null);
  const tickRef = useRef<number | null>(null);
  const limitRef = useRef<number | null>(null);
  const doneRef = useRef<number | null>(null);
  const startedAtRef = useRef(0);
  const startChatRef = useRef<string | null>(null);
  const captureIdRef = useRef(0);
  const uploadStartedRef = useRef<number | null>(null);
  const chatIdRef = useRef(chatId);
  const enabledRef = useRef(enabled);
  const disabledRef = useRef(disabled);
  const readinessRef = useRef(readiness);
  const maxSecondsRef = useRef(maxRecordingSeconds);
  const onTranscriptRef = useRef(onTranscript);

  useEffect(() => {
    chatIdRef.current = chatId;
    enabledRef.current = enabled;
    disabledRef.current = disabled;
    maxSecondsRef.current = maxRecordingSeconds;
    onTranscriptRef.current = onTranscript;
    readinessRef.current = readiness;
  }, [chatId, enabled, disabled, maxRecordingSeconds, onTranscript, readiness]);

  const applyPhase = useCallback((next: SpeechPhase) => {
    phaseRef.current = next;
    if (mountedRef.current) setPhase(next);
  }, []);

  const clearTimers = useCallback(() => {
    if (tickRef.current !== null) window.clearInterval(tickRef.current);
    if (limitRef.current !== null) window.clearTimeout(limitRef.current);
    if (doneRef.current !== null) window.clearTimeout(doneRef.current);
    tickRef.current = null;
    limitRef.current = null;
    doneRef.current = null;
  }, []);

  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const resetCapture = useCallback(() => {
    clearTimers();
    releaseStream();
    recorderRef.current = null;
    recorderMimeRef.current = null;
  }, [clearTimers, releaseStream]);

  const discardRecorder = useCallback(() => {
    const recorder = recorderRef.current;
    if (!recorder) return;
    recorder.ondataavailable = null;
    recorder.onstop = null;
    recorder.onerror = null;
    if (recorder.state !== 'inactive') {
      try {
        recorder.stop();
      } catch {
        // Already stopped; nothing is retained.
      }
    }
  }, []);

  const lastErrorCodeRef = useRef<string | null>(null);
  const fail = useCallback((message: string, code: string = 'speech_upstream_error') => {
    discardRecorder();
    resetCapture();
    chunksRef.current = [];
    lastErrorCodeRef.current = code;
    if (mountedRef.current) {
      setError(message);
      setElapsedMs(0);
    }
    applyPhase('error');
  }, [applyPhase, discardRecorder, resetCapture]);

  const upload = useCallback(async (captureId = captureIdRef.current) => {
    if (captureId !== captureIdRef.current || uploadStartedRef.current === captureId) {
      return;
    }
    uploadStartedRef.current = captureId;
    const chunks = chunksRef.current;
    chunksRef.current = [];
    const mime =
      recorderMimeRef.current ||
      recorderRef.current?.mimeType ||
      chunks.find((chunk) => chunk.type)?.type ||
      'audio/webm';
    const audio = new Blob(chunks, { type: mime });
    resetCapture();
    if (!mountedRef.current) return;
    if (startChatRef.current !== chatIdRef.current) {
      applyPhase('idle');
      return;
    }
    if (audio.size === 0) {
      fail(formatSpeechError('recording_failed'), 'recording_failed');
      return;
    }
    applyPhase('uploading');
    setError(null);
    const controller = new AbortController();
    requestRef.current = controller;
    try {
      await transcribeAudio(audio, {
        signal: controller.signal,
        onEvent: (event) => {
          // A cancelled capture can still deliver a buffered stream event while
          // a new recording is starting. Never let the old stream mutate the
          // new capture's phase, timer or composer.
          if (captureId !== captureIdRef.current) return;
          if (!mountedRef.current || startChatRef.current !== chatIdRef.current) return;
          if (event.type === 'queued') applyPhase('queued');
          if (event.type === 'processing') applyPhase('processing');
          if (event.type === 'error') {
            throw new SpeechRequestError(event.message, event.code);
          }
          if (event.type === 'result') {
            const targetChat = startChatRef.current;
            if (!targetChat) return;
            const insertionError = onTranscriptRef.current(event.text, targetChat);
            if (insertionError) {
              fail(insertionError);
              return;
            }
            if (!mountedRef.current) return;
            setError(null);
            setElapsedMs(0);
            applyPhase('done');
            doneRef.current = window.setTimeout(() => {
              if (
                mountedRef.current &&
                captureIdRef.current === captureId &&
                phaseRef.current === 'done'
              ) {
                applyPhase('idle');
              }
            }, 1800);
          }
        },
      });
    } catch (caught) {
      // The capture may have been cancelled (or cancelled and replaced) while
      // this request was rejecting. Its late result must not touch newer state.
      if (captureId !== captureIdRef.current) return;
      if ((caught as Error)?.name === 'AbortError') {
        if (mountedRef.current) applyPhase('idle');
        return;
      }
      const code = caught instanceof SpeechRequestError ? caught.code : 'speech_upstream_error';
      fail(formatSpeechError(code), code);
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
      // Do not clear chunksRef here: a newer capture may already be recording.
    }
  }, [applyPhase, fail, resetCapture]);

  const stop = useCallback(() => {
    if (phaseRef.current !== 'recording') return;
    const recorder = recorderRef.current;
    clearTimers();
    applyPhase('uploading');
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop();
      } catch {
        fail(formatSpeechError('recording_failed'), 'recording_failed');
        return;
      }
    } else {
      void upload(captureIdRef.current);
    }
  }, [applyPhase, clearTimers, fail, upload]);

  const cancel = useCallback(() => {
    captureIdRef.current += 1;
    clearTimers();
    requestRef.current?.abort();
    requestRef.current = null;
    discardRecorder();
    chunksRef.current = [];
    resetCapture();
    if (mountedRef.current) {
      setError(null);
      setElapsedMs(0);
    }
    applyPhase('idle');
  }, [applyPhase, clearTimers, discardRecorder, resetCapture]);

  const start = useCallback(() => {
    if (!enabledRef.current || disabledRef.current || !chatIdRef.current) return;
    if (readinessRef.current !== 'ready') return;
    if (ACTIVE_PHASES.includes(phaseRef.current)) return;
    if (typeof window === 'undefined' || typeof navigator === 'undefined') return;
    if (!window.isSecureContext) {
      fail(formatSpeechError('not_secure_context'));
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      fail(formatSpeechError('unsupported_browser'));
      return;
    }
    const targetChat = chatIdRef.current;
    const captureId = captureIdRef.current + 1;
    captureIdRef.current = captureId;
    startChatRef.current = targetChat;
    setError(null);
    setElapsedMs(0);
    applyPhase('requesting');

    void (async () => {
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
          },
        });
      } catch (caught) {
        if (captureIdRef.current !== captureId) return;
        const name = (caught as Error)?.name;
        fail(
          name === 'NotAllowedError' || name === 'SecurityError'
            ? formatSpeechError('permission_denied')
            : name === 'NotFoundError' || name === 'DevicesNotFoundError'
              ? formatSpeechError('microphone_unavailable')
              : formatSpeechError('recording_failed'),
          name === 'NotAllowedError' || name === 'SecurityError'
            ? 'permission_denied'
            : name === 'NotFoundError' || name === 'DevicesNotFoundError'
              ? 'microphone_unavailable'
              : 'recording_failed',
        );
        return;
      }
      if (
        !mountedRef.current ||
        captureIdRef.current !== captureId ||
        startChatRef.current !== chatIdRef.current ||
        disabledRef.current
      ) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      let recorder: MediaRecorder;
      try {
        const mime = pickRecorderMime((type) => MediaRecorder.isTypeSupported(type));
        recorderMimeRef.current = mime;
        recorder = mime
          ? new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 64000 })
          : new MediaRecorder(stream);
      } catch {
        fail(formatSpeechError('recording_failed'), 'recording_failed');
        return;
      }
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onerror = () => fail(formatSpeechError('recording_failed'));
      recorder.onstop = () => {
        void upload(captureId);
      };
      try {
        recorder.start(250);
      } catch {
        fail(formatSpeechError('recording_failed'), 'recording_failed');
        return;
      }
      applyPhase('recording');
      startedAtRef.current = performance.now();
      setElapsedMs(0);
      tickRef.current = window.setInterval(() => {
        if (mountedRef.current) setElapsedMs(performance.now() - startedAtRef.current);
      }, 250);
      limitRef.current = window.setTimeout(() => {
        stop();
      }, maxSecondsRef.current * 1000);
    })();
  }, [applyPhase, fail, stop, upload]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      captureIdRef.current += 1;
      clearTimers();
      requestRef.current?.abort();
      discardRecorder();
      releaseStream();
      chunksRef.current = [];
    };
  }, [clearTimers, discardRecorder, releaseStream]);

  useEffect(() => {
    // Speech state belongs to the chat where capture started. Switching chats
    // cancels an active capture and also clears a stale error/completion state
    // so the next chat never inherits it.
    if (startChatRef.current && chatId !== startChatRef.current) {
      cancel();
    }
  }, [chatId, cancel]);

  useEffect(() => {
    if (disabled && ACTIVE_PHASES.includes(phaseRef.current)) cancel();
  }, [cancel, disabled]);

  useEffect(() => {
    if (!enabled && ACTIVE_PHASES.includes(phaseRef.current)) cancel();
  }, [cancel, enabled]);

  useEffect(() => {
    // A transient service outage must not leave a stale error once the
    // backend verifies recovery. Only availability-class errors are cleared;
    // device/permission errors remain for the user to address.
    if (readiness === 'ready' && phaseRef.current === 'error' && isSpeechAvailabilityError(lastErrorCodeRef.current ?? '')) {
      lastErrorCodeRef.current = null;
      if (mountedRef.current) {
        setError(null);
        setElapsedMs(0);
      }
      applyPhase('idle');
    }
  }, [readiness, applyPhase]);

  return {
    phase,
    error,
    elapsedMs,
    maxSeconds: maxRecordingSeconds,
    start,
    stop,
    cancel,
  };
}
