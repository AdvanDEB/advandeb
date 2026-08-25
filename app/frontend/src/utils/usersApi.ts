/**
 * Typed helpers for the admin user-management API (/api/users).
 *
 * All of these require the caller to hold the `administrator` role; the
 * backend enforces this (403 otherwise), the frontend just gates the route.
 */
import api from './api'
import type {
  AdminUser,
  CreateUserPayload,
  UserListParams,
  UserListResponse,
} from '@/types/user'

const BASE = '/users'

// Excludes visually ambiguous characters (0/O, 1/l/I) — mirrors the backend
// generator in app/backend/app/services/user_service.py.
const PASSWORD_ALPHABET =
  'ABCDEFGHJKLMNPQRSTUVWXYZ' + 'abcdefghijkmnpqrstuvwxyz' + '23456789' + '!@#%*+-='

/** Generate a strong random password client-side for the create-user form. */
export function generatePassword(length = 14): string {
  const bytes = new Uint32Array(length)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => PASSWORD_ALPHABET[b % PASSWORD_ALPHABET.length]).join('')
}

/** List users with optional search/role/status filters and pagination. */
export async function listUsers(params: UserListParams): Promise<UserListResponse> {
  const { data } = await api.get<UserListResponse>(`${BASE}/`, { params })
  return data
}

/** Create a native email/password user (admin only). */
export async function createUser(payload: CreateUserPayload): Promise<AdminUser> {
  const { data } = await api.post<AdminUser>(`${BASE}/`, payload)
  return data
}

/** Add a role to a user. */
export async function assignRole(userId: string, role: string): Promise<AdminUser> {
  const { data } = await api.post<AdminUser>(`${BASE}/${userId}/roles`, null, { params: { role } })
  return data
}

/** Remove a role from a user. */
export async function removeRole(userId: string, role: string): Promise<AdminUser> {
  const { data } = await api.delete<AdminUser>(`${BASE}/${userId}/roles/${role}`)
  return data
}

/** Suspend or reactivate a user's account. */
export async function setStatus(userId: string, status: 'active' | 'suspended'): Promise<AdminUser> {
  const { data } = await api.patch<AdminUser>(`${BASE}/${userId}/status`, { status })
  return data
}

/** Permanently delete a user. */
export async function deleteUser(userId: string): Promise<void> {
  await api.delete(`${BASE}/${userId}`)
}

/** Generate and set a new password for a user; returned once, not stored. */
export async function resetPassword(userId: string): Promise<{ password: string }> {
  const { data } = await api.post<{ password: string }>(`${BASE}/${userId}/reset-password`)
  return data
}

/** Get a single user by id (admin only). */
export async function getUser(userId: string): Promise<AdminUser> {
  const { data } = await api.get<AdminUser>(`${BASE}/${userId}`)
  return data
}

/** Update the current user's own profile, e.g. the chat-visibility opt-out. */
export async function updateMyProfile(payload: {
  full_name?: string
  avatar_url?: string
  chat_history_visible_to_admin?: boolean
}): Promise<AdminUser> {
  const { data } = await api.put<AdminUser>(`${BASE}/me`, payload)
  return data
}
