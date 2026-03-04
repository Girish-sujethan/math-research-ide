"use client"

import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { ChatResponse } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Send } from "lucide-react"

interface Message {
  role: "user" | "assistant"
  content: string
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [sessionId, setSessionId] = useState<string | undefined>()

  const chatMutation = useMutation({
    mutationFn: (text: string) => api.chat(text, sessionId),
    onSuccess: (res: ChatResponse) => {
      setSessionId(res.session_id)
      setMessages(prev => [...prev, { role: "assistant", content: res.reply }])
    },
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const text = input.trim()
    if (!text) return
    setMessages(prev => [...prev, { role: "user", content: text }])
    setInput("")
    chatMutation.mutate(text)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e as unknown as React.FormEvent)
    }
  }

  return (
    <div className="flex h-full flex-col p-6">
      <h1 className="mb-4 text-xl font-semibold">Chat</h1>

      <ScrollArea className="flex-1 rounded-lg border p-4">
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Ask about mathematical concepts, request analyses, or explore the knowledge graph…
          </p>
        )}
        <div className="flex flex-col gap-3">
          {messages.map((msg, i) => (
            <div key={i} className={msg.role === "user" ? "self-end max-w-xl" : "self-start max-w-2xl"}>
              <div
                className={`rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted"
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}
          {chatMutation.isPending && (
            <div className="self-start rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
              Thinking…
            </div>
          )}
          {chatMutation.isError && (
            <div className="self-start rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {(chatMutation.error as Error).message}
            </div>
          )}
        </div>
      </ScrollArea>

      <form onSubmit={handleSubmit} className="mt-3 flex gap-2">
        <Textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Send a message… (Enter to send, Shift+Enter for newline)"
          className="resize-none"
          rows={2}
        />
        <Button
          type="submit"
          size="icon"
          disabled={chatMutation.isPending || !input.trim()}
        >
          <Send className="size-4" />
        </Button>
      </form>
    </div>
  )
}
