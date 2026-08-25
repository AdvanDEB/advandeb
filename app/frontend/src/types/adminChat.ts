/**
 * Type definitions for admin read-only chat access (/api/users/{id}/chat/*)
 * and the access-log audit trail both admins and users can see.
 */
import type { ChatMessage } from './chat'

export interface AdminChatSession {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface AdminChatSessionDetail extends AdminChatSession {
  messages: ChatMessage[]
}

export interface ChatAccessLogEntry {
  admin_email: string
  /** null when the entry is from a session-list view rather than opening one session. */
  session_id: string | null
  accessed_at: string
}
