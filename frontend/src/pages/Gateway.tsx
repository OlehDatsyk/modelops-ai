import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Card, CardHeader, CopyButton, PageHeader, Tabs } from '../components/ui'

function Code({ code }: { code: string }) {
  return (
    <div className="relative">
      <div className="absolute top-2 right-2"><CopyButton value={code} /></div>
      <pre className="mono overflow-x-auto rounded-lg border border-line bg-bg-2 p-4 pr-24 leading-relaxed text-ink-2">{code}</pre>
    </div>
  )
}

type Lang = 'curl' | 'python' | 'node'

export default function Gateway() {
  const base = `${window.location.origin}/api/v1/gateway`
  const [lang, setLang] = useState<Lang>('curl')
  const key = 'mk_YOUR_PROJECT_KEY'

  const examples: Record<Lang, { title: string; code: string }[]> = {
    curl: [
      { title: 'OpenAI — Chat Completions', code: `curl ${base}/openai/chat/completions \\\n  -H "Authorization: Bearer ${key}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hello"}]}'` },
      { title: 'Anthropic — Messages', code: `curl ${base}/anthropic/messages \\\n  -H "x-api-key: ${key}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "claude-haiku-4-5", "max_tokens": 256, "messages": [{"role": "user", "content": "Hello"}]}'` },
      { title: 'Gemini — generateContent', code: `curl ${base}/gemini/generate \\\n  -H "Authorization: Bearer ${key}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "gemini-2.5-flash", "contents": [{"role": "user", "parts": [{"text": "Hello"}]}]}'` },
      { title: 'Streaming (any provider)', code: `curl -N ${base}/openai/chat/completions \\\n  -H "Authorization: Bearer ${key}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "gpt-4o-mini", "stream": true, "messages": [{"role": "user", "content": "Count to 5"}]}'` },
    ],
    python: [
      { title: 'OpenAI SDK', code: `from openai import OpenAI\n\nclient = OpenAI(api_key="${key}", base_url="${base}/openai")\nreply = client.chat.completions.create(\n    model="gpt-4o-mini",\n    messages=[{"role": "user", "content": "Hello"}],\n)\nprint(reply.choices[0].message.content)` },
      { title: 'Anthropic SDK', code: `import anthropic\n\nclient = anthropic.Anthropic(api_key="${key}", base_url="${base}/anthropic")\nmessage = client.messages.create(\n    model="claude-haiku-4-5",\n    max_tokens=256,\n    messages=[{"role": "user", "content": "Hello"}],\n)\nprint(message.content[0].text)` },
      { title: 'Google Gen AI SDK', code: `from google import genai\nfrom google.genai import types\n\nclient = genai.Client(\n    api_key="${key}",\n    http_options=types.HttpOptions(base_url="${base}/gemini"),\n)\nresponse = client.models.generate_content(model="gemini-2.5-flash", contents="Hello")\nprint(response.text)` },
    ],
    node: [
      { title: 'OpenAI SDK', code: `import OpenAI from 'openai'\n\nconst client = new OpenAI({ apiKey: '${key}', baseURL: '${base}/openai' })\nconst reply = await client.chat.completions.create({\n  model: 'gpt-4o-mini',\n  messages: [{ role: 'user', content: 'Hello' }],\n})\nconsole.log(reply.choices[0].message.content)` },
      { title: 'Anthropic SDK', code: `import Anthropic from '@anthropic-ai/sdk'\n\nconst client = new Anthropic({ apiKey: '${key}', baseURL: '${base}/anthropic' })\nconst message = await client.messages.create({\n  model: 'claude-haiku-4-5',\n  max_tokens: 256,\n  messages: [{ role: 'user', content: 'Hello' }],\n})\nconsole.log(message.content)` },
      { title: 'fetch (Gemini)', code: `const res = await fetch('${base}/gemini/generate', {\n  method: 'POST',\n  headers: { Authorization: 'Bearer ${key}', 'Content-Type': 'application/json' },\n  body: JSON.stringify({ model: 'gemini-2.5-flash', contents: [{ parts: [{ text: 'Hello' }] }] }),\n})\nconsole.log(await res.json())` },
    ],
  }

  return (
    <>
      <PageHeader title="Gateway quickstart" description="Point your existing SDKs at the ModelOps gateway. Requests are forwarded to the provider with your stored key, and their metadata is recorded." />
      <div className="mb-5 grid gap-4 md:grid-cols-3">
        {[
          ['1', 'Add a provider key', 'Store your OpenAI, Anthropic or Gemini key (encrypted).', '/providers'],
          ['2', 'Create a project key', 'Each project gets mk_… keys for gateway authentication.', '/projects'],
          ['3', 'Change the base URL', 'Use the examples below. Responses are returned unchanged.', ''],
        ].map(([n, t, d, to]) => (
          <Card key={n} className="p-4">
            <div className="flex items-center gap-3">
              <span className="grid size-7 place-items-center rounded-full bg-accent/15 text-sm font-semibold text-accent">{n}</span>
              <span className="font-medium">{to ? <Link to={to} className="hover:text-accent">{t}</Link> : t}</span>
            </div>
            <p className="mt-2 text-sm text-muted">{d}</p>
          </Card>
        ))}
      </div>
      <Card className="mb-5">
        <CardHeader title="Endpoints" subtitle="Authenticate with a project key via Authorization: Bearer, x-api-key or x-goog-api-key." />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px]">
            <tbody>
              {[
                ['POST', '/openai/chat/completions', 'OpenAI Chat Completions (stream supported)'],
                ['POST', '/anthropic/messages', 'Anthropic Messages (also /anthropic/v1/messages; stream supported)'],
                ['POST', '/gemini/generate', 'Gemini generateContent — model and optional stream flag in the body'],
                ['POST', '/gemini/v1beta/models/{model}:generateContent', 'Gemini native path (also :streamGenerateContent, SSE)'],
              ].map(([m, path, d]) => (
                <tr key={path} className="border-b border-line/40 last:border-0">
                  <td className="td w-16"><span className="mono rounded bg-accent/15 px-1.5 py-0.5 text-accent">{m}</span></td>
                  <td className="td mono text-ink">{base}{path}</td>
                  <td className="td">{d}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Tabs<Lang> tabs={[{ key: 'curl', label: 'cURL' }, { key: 'python', label: 'Python' }, { key: 'node', label: 'Node.js' }]} value={lang} onChange={setLang} />
      <div className="space-y-5">
        {examples[lang].map((ex) => (
          <div key={ex.title}>
            <h3 className="mb-2 text-sm font-medium text-ink-2">{ex.title}</h3>
            <Code code={ex.code} />
          </div>
        ))}
      </div>
      <Alert tone="info" className="mt-6">
        Every response includes an <code className="mono">x-modelops-request-id</code> header you can search for in Request logs. For OpenAI streaming the
        gateway sets <code className="mono">stream_options.include_usage</code> so token usage can be recorded. Error responses from providers are passed
        through unchanged; gateway errors use the format <code className="mono">{'{"error": {"code", "message", "request_id"}}'}</code>.
      </Alert>
    </>
  )
}
