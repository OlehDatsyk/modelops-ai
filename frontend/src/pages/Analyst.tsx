import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bot, ChevronDown, MessageSquarePlus, Send, Trash2, User as UserIcon } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Alert, Button, Card, EmptyState, ErrorState, LoadingBlock, PageHeader } from '../components/ui'
import { api, errorMessage } from '../lib/api'
import { formatRelative } from '../lib/format'
import type { AnalystMessage, AnalystStatus, Conversation, ConversationDetail } from '../lib/types'

const SUGGESTIONS = [
  'Why did my API costs increase this week?',
  'Which model is the most expensive?',
  'Which provider has the highest failure rate?',
  'How much money did I spend yesterday?',
  'Which project consumes the most tokens?',
  'What can I do to reduce my API costs?',
]

/** Minimal, safe rendering of the assistant's markdown-ish text (bold, bullets, paragraphs). No HTML injection. */
function RichText({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/)
  const inline = (s: string) =>
    s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
      part.startsWith('**') && part.endsWith('**') ? (
        <strong key={i} className="font-semibold text-ink">{part.slice(2, -2)}</strong>
      ) : part.startsWith('`') && part.endsWith('`') ? (
        <code key={i} className="mono rounded bg-surface-3 px-1 py-0.5">{part.slice(1, -1)}</code>
      ) : (
        part
      ),
    )
  return (
    <div className="space-y-2.5 text-sm leading-relaxed text-ink-2">
      {blocks.map((block, i) => {
        const lines = block.split('\n')
        if (lines.every((l) => /^\s*([-*•]|\d+\.)\s+/.test(l))) {
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*([-*•]|\d+\.)\s+/, ''))}</li>)}
            </ul>
          )
        }
        return <p key={i} className="whitespace-pre-wrap">{inline(block.replace(/^#+\s*/, ''))}</p>
      })}
    </div>
  )
}

function Evidence({ message }: { message: AnalystMessage }) {
  const [open, setOpen] = useState(false)
  if (!message.tool_results.length) return null
  return (
    <div className="mt-3">
      <button className="inline-flex items-center gap-1 text-xs text-accent hover:underline" onClick={() => setOpen((o) => !o)}>
        <ChevronDown className={clsx('size-3.5 transition-transform', open && 'rotate-180')} />
        Supporting data ({message.tool_results.length} {message.tool_results.length === 1 ? 'query' : 'queries'})
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {message.tool_results.map((e, i) => (
            <details key={i} className="rounded-lg border border-line bg-bg-2">
              <summary className="cursor-pointer px-3 py-2 text-xs text-ink-2">
                <span className="mono text-ink">{e.tool}</span> <span className="text-muted">{JSON.stringify(e.args)}</span>
              </summary>
              <pre className="mono max-h-72 overflow-auto border-t border-line px-3 py-2 text-[11.5px] text-muted">{JSON.stringify(e.result, null, 2)}</pre>
            </details>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Analyst() {
  const qc = useQueryClient()
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const status = useQuery({ queryKey: ['analyst-status'], queryFn: () => api<AnalystStatus>('/analyst/status') })
  const conversations = useQuery({ queryKey: ['conversations'], queryFn: () => api<Conversation[]>('/analyst/conversations') })
  const detail = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => api<ConversationDetail>(`/analyst/conversations/${conversationId}`),
    enabled: !!conversationId,
  })

  const ask = useMutation({
    mutationFn: (q: string) =>
      api<{ conversation: Conversation }>('/analyst/ask', { method: 'POST', body: { question: q, conversation_id: conversationId } }),
    onMutate: (q) => setPending(q),
    onSuccess: (res) => {
      setConversationId(res.conversation.id)
      qc.invalidateQueries({ queryKey: ['conversations'] })
      qc.invalidateQueries({ queryKey: ['conversation', res.conversation.id] })
      setQuestion('')
    },
    onSettled: () => setPending(null),
  })
  const remove = useMutation({
    mutationFn: (id: string) => api(`/analyst/conversations/${id}`, { method: 'DELETE' }),
    onSuccess: (_, id) => {
      if (id === conversationId) setConversationId(null)
      qc.invalidateQueries({ queryKey: ['conversations'] })
    },
  })

  const messages = conversationId ? detail.data?.messages ?? [] : []
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, pending])

  const submit = (e?: FormEvent, text?: string) => {
    e?.preventDefault()
    const q = (text ?? question).trim()
    if (q.length >= 2 && !ask.isPending) ask.mutate(q)
  }
  const configured = status.data?.configured

  return (
    <>
      <PageHeader
        title="AI Analyst"
        description="Ask questions about your usage, costs and failures. Answers are generated from your own analytics through a fixed set of read-only queries."
      />
      {status.data && !configured && (
        <Alert tone="warn" className="mb-4">
          The AI Analyst is not configured on this server. An administrator must set <code className="mono">AI_ANALYST_PROVIDER</code>,{' '}
          <code className="mono">AI_ANALYST_MODEL</code> and <code className="mono">AI_ANALYST_API_KEY</code> (see INSTRUCTION.md).
        </Alert>
      )}
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <Card className="h-fit lg:sticky lg:top-20">
          <div className="border-b border-line/70 p-3">
            <Button className="w-full" icon={<MessageSquarePlus className="size-4" />} onClick={() => setConversationId(null)}>New conversation</Button>
          </div>
          <div className="max-h-[50vh] overflow-y-auto p-2 lg:max-h-[60vh]">
            {conversations.isLoading ? <LoadingBlock className="py-6" /> : !conversations.data?.length ? (
              <p className="px-2 py-6 text-center text-xs text-muted">No conversations yet.</p>
            ) : (
              conversations.data.map((c) => (
                <div key={c.id} className={clsx('group flex items-center gap-1 rounded-md', c.id === conversationId ? 'bg-surface-2' : 'hover:bg-surface-2/60')}>
                  <button onClick={() => setConversationId(c.id)} className="min-w-0 flex-1 px-2.5 py-2 text-left">
                    <p className="truncate text-sm text-ink-2">{c.title}</p>
                    <p className="text-[11px] text-faint">{formatRelative(c.updated_at)}</p>
                  </button>
                  <button onClick={() => remove.mutate(c.id)} className="mr-1 rounded p-1.5 text-faint opacity-0 group-hover:opacity-100 hover:text-bad focus:opacity-100" aria-label="Delete conversation">
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card className="flex min-h-[60vh] flex-col">
          <div ref={scrollRef} className="flex-1 space-y-5 overflow-y-auto p-5" style={{ maxHeight: '65vh' }}>
            {conversationId && detail.isLoading ? (
              <LoadingBlock />
            ) : conversationId && detail.isError ? (
              <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
            ) : !messages.length && !pending ? (
              <EmptyState
                icon={<Bot className="size-5" />}
                title="Ask about your AI API usage"
                description="The analyst can summarise spend, compare periods, break down usage by provider, model or project, analyse errors and suggest savings."
                action={
                  <div className="flex max-w-2xl flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((s) => (
                      <button key={s} disabled={!configured || ask.isPending} onClick={() => submit(undefined, s)} className="rounded-full border border-line bg-surface-2 px-3 py-1.5 text-xs text-ink-2 hover:border-accent/50 hover:text-ink disabled:opacity-50">
                        {s}
                      </button>
                    ))}
                  </div>
                }
              />
            ) : (
              <>
                {messages.map((m) => (
                  <div key={m.id} className="flex gap-3">
                    <div className={clsx('grid size-7 shrink-0 place-items-center rounded-full', m.role === 'user' ? 'bg-surface-3 text-ink-2' : 'bg-gradient-to-br from-accent to-accent-2 text-white')}>
                      {m.role === 'user' ? <UserIcon className="size-3.5" /> : <Bot className="size-3.5" />}
                    </div>
                    <div className="min-w-0 flex-1 pt-0.5">
                      {m.role === 'user' ? <p className="text-sm font-medium text-ink">{m.content}</p> : <RichText text={m.content} />}
                      {m.role === 'assistant' && <Evidence message={m} />}
                    </div>
                  </div>
                ))}
                {pending && (
                  <>
                    <div className="flex gap-3">
                      <div className="grid size-7 shrink-0 place-items-center rounded-full bg-surface-3 text-ink-2"><UserIcon className="size-3.5" /></div>
                      <p className="pt-1 text-sm font-medium text-ink">{pending}</p>
                    </div>
                    <div className="flex items-center gap-3 text-sm text-muted">
                      <div className="grid size-7 place-items-center rounded-full bg-gradient-to-br from-accent to-accent-2 text-white"><Bot className="size-3.5" /></div>
                      <span className="animate-pulse">Querying your analytics…</span>
                    </div>
                  </>
                )}
              </>
            )}
            {ask.isError && <Alert tone="bad">{errorMessage(ask.error)}</Alert>}
          </div>
          <form onSubmit={submit} className="flex gap-2 border-t border-line/70 p-3">
            <input
              className="input h-10"
              placeholder={configured ? 'Ask a question about your usage…' : 'AI Analyst is not configured'}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={2000}
              disabled={!configured}
              aria-label="Question"
            />
            <Button type="submit" variant="primary" className="h-10" loading={ask.isPending} disabled={!configured || question.trim().length < 2} icon={<Send className="size-4" />}>
              Ask
            </Button>
          </form>
        </Card>
      </div>
    </>
  )
}
