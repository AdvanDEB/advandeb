/**
 * Typed helpers for read-only admin chat access (/api/users/{id}/chat/*)
 * and the access-log audit trail (both the admin-facing and self-facing views).
 */
import api from './api'
import type { AdminChatSession, AdminChatSessionDetail, ChatAccessLogEntry } from '@/types/adminChat'

const BASE = '/users'

/** List a user's chat sessions (admin only). 403 if the user opted out. */
export async function listUserSessions(userId: string): Promise<AdminChatSession[]> {
  const { data } = await api.get<AdminChatSession[]>(`${BASE}/${userId}/chat/sessions`)
  return data
}

/** Fetch one of a user's sessions with its messages (admin only). */
export async function getUserSession(userId: string, sessionId: string): Promise<AdminChatSessionDetail> {
  const { data } = await api.get<AdminChatSessionDetail>(`${BASE}/${userId}/chat/sessions/${sessionId}`)
  return data
}

/** List past staff accesses to a user's chat history (admin only). */
export async function getUserAccessLog(userId: string): Promise<ChatAccessLogEntry[]> {
  const { data } = await api.get<ChatAccessLogEntry[]>(`${BASE}/${userId}/chat-access-log`)
  return data
}

/** List which staff members have accessed the current user's own chat history. */
export async function getMyAccessLog(): Promise<ChatAccessLogEntry[]> {
  const { data } = await api.get<ChatAccessLogEntry[]>(`${BASE}/me/chat-access-log`)
  return data
}
