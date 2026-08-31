import { useParams, useNavigate, Link } from 'react-router-dom'
import { ArrowLeft, FileText, Gauge, CheckCircle2, Target } from 'lucide-react'
import TopBar from '../components/TopBar.jsx'
import Card from '../components/Card.jsx'
import AudioPlayer from '../components/AudioPlayer.jsx'
import Transcript from '../components/Transcript.jsx'
import MoodTimeline from '../components/MoodTimeline.jsx'
import EvidenceChip from '../components/EvidenceChip.jsx'
import ScorePill from '../components/ScorePill.jsx'
import ResolutionPill from '../components/ResolutionPill.jsx'
import { LoadingState, ErrorState } from '../components/PageState.jsx'
import { AudioPlayerProvider } from '../context/AudioPlayerContext.jsx'
import { useApi } from '../hooks/useApi.js'
import { getCall, getCallAudioUrl } from '../api/client.js'
import { formatDateTime, formatDuration, initials, titleCase } from '../utils/format.js'
import { parseRepeatContact } from '../utils/attentionReason.js'
import { scoreColor } from '../utils/scoreBands.js'
import { getAvatarColor } from '../utils/avatarColor.js'

function CallDetailContent({ call }) {
  const repeat = call.attention_reasons?.find((r) => parseRepeatContact(r.reason))
  const repeatInfo = repeat ? parseRepeatContact(repeat.reason) : null

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_380px]">
      {/* Left column: audio + transcript */}
      <div className="min-w-0 space-y-4">
        <div className="sticky top-0 z-10 -mt-1 bg-app-bg pb-1 pt-1">
          <AudioPlayer
            callId={call.call_id}
            src={getCallAudioUrl(call.call_id)}
            moodEvents={call.mood_events}
            moodShiftSegmentId={call.mood_shift_segment_id}
            durationSeconds={call.duration_seconds}
          />
        </div>
        <Card title="Transcript">
          <Transcript segments={call.transcript} moodShiftSegmentId={call.mood_shift_segment_id} />
        </Card>
      </div>

      {/* Right column: stacked evidence-backed judgment cards */}
      <div className="space-y-4">
        <Card title="Summary" icon={FileText}>
          <p className="text-sm leading-relaxed text-app-text">{call.summary || 'No summary available.'}</p>
        </Card>

        <Card title="Mood timeline" icon={Gauge}>
          <MoodTimeline
            initialMood={call.initial_mood}
            finalMood={call.final_mood}
            moodEvents={call.mood_events}
            moodShiftSegmentId={call.mood_shift_segment_id}
            durationSeconds={call.duration_seconds}
          />
        </Card>

        <Card title="Attention score" icon={Target}>
          <div className="flex items-center gap-3">
            <ScorePill score={call.attention_score} size="lg" showBandLabel />
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-app-border">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.min(100, call.attention_score ?? 0)}%`,
                  backgroundColor: scoreColor(call.attention_score),
                }}
              />
            </div>
          </div>
          {call.attention_reasons?.length > 0 ? (
            <ul className="mt-4 space-y-2.5">
              {call.attention_reasons.map((r, i) => {
                const linked = parseRepeatContact(r.reason)
                return (
                  <li key={i} className="flex flex-col gap-1.5 border-t border-app-border pt-2.5 first:border-t-0 first:pt-0">
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-sm text-app-text">{r.reason}</span>
                      <span className="shrink-0 rounded-md bg-app-border/70 px-1.5 py-0.5 font-mono-data text-xs text-app-text-secondary">
                        +{r.points}
                      </span>
                    </div>
                    <EvidenceChip
                      timestamp={r.evidence_start_time}
                      quote={r.evidence_text}
                      segmentId={r.evidence_segment_id}
                      linkedCallId={linked?.callId}
                      linkedDate={linked?.date}
                    />
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-app-text-secondary">No attention reasons triggered.</p>
          )}
        </Card>

        <Card title="Resolution" icon={CheckCircle2}>
          <div className="flex items-center justify-between">
            <ResolutionPill resolution={call.resolution} />
          </div>
          <div className="mt-2">
            <EvidenceChip
              segmentId={call.resolution_evidence_segment_id}
              timestamp={call.resolution_evidence_start_time}
              quote={call.resolution_evidence_text}
            />
          </div>
        </Card>

        <Card title="Intent">
          <p className="text-sm text-app-text">{titleCase(call.intent) || 'Unknown'}</p>
          <div className="mt-2">
            <EvidenceChip
              segmentId={call.ai_evidence?.intent_evidence?.segment_id}
              timestamp={call.ai_evidence?.intent_evidence?.start_time}
              quote={call.ai_evidence?.intent_evidence?.text}
            />
          </div>
        </Card>

        {repeatInfo && (
          <Card title="Customer history">
            <p className="text-sm text-app-text-secondary">This customer contacted support before.</p>
            <div className="mt-2">
              <EvidenceChip linkedCallId={repeatInfo.callId} linkedDate={repeatInfo.date} />
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}

export default function CallDetail() {
  const { callId } = useParams()
  const navigate = useNavigate()
  const { data: call, loading, error } = useApi(() => getCall(callId), [callId])

  return (
    <>
      <TopBar>
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="mb-1.5 inline-flex items-center gap-1.5 rounded-md border border-app-border bg-app-panel px-3 py-1.5 text-sm font-medium text-app-text-secondary transition hover:border-app-accent hover:text-app-text"
        >
          <ArrowLeft size={15} /> Back
        </button>
        {call && (
          <div className="flex flex-wrap items-center gap-2">
            <span
              style={{ background: getAvatarColor(call.customer?.name || '') }}
              className="flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-semibold text-white"
            >
              {initials(call.customer?.name)}
            </span>
            <h1 className="text-lg font-semibold text-app-text">{call.customer?.name || 'Unknown customer'}</h1>
            <span className="text-sm text-app-text-secondary">
              with {call.agent?.name || 'unknown agent'} · {formatDateTime(call.started_at)} ·{' '}
              {formatDuration(call.duration_seconds)}
            </span>
          </div>
        )}
      </TopBar>

      <main className="flex-1 overflow-y-auto p-6">
        {loading && <LoadingState label="Loading call…" />}
        {!loading && error && (
          <ErrorState
            message={
              error?.response?.status === 404
                ? 'This call was not found (or has not been processed yet).'
                : "Couldn't load this call."
            }
          />
        )}
        {!loading && !error && call && (
          <>
            <div className="mb-5 flex flex-wrap items-center gap-2">
              <span className="rounded-full border border-app-border px-2.5 py-1 text-xs text-app-text-secondary">
                {titleCase(call.intent) || 'Unknown intent'}
              </span>
              <ResolutionPill resolution={call.resolution} />
              <ScorePill score={call.attention_score} size="sm" />
              <span className="ml-auto font-mono-data text-xs text-app-text-secondary" title="Call ID">
                {call.call_id}
              </span>
              {call.customer?.id && (
                <Link
                  to={`/customers/${call.customer.id}`}
                  className="text-xs text-app-accent hover:underline"
                >
                  View customer →
                </Link>
              )}
            </div>
            <AudioPlayerProvider>
              <CallDetailContent call={call} />
            </AudioPlayerProvider>
          </>
        )}
      </main>
    </>
  )
}
