/**
 * Type definitions for admin user management (/api/users).
 */

export type UserRole = 'administrator' | 'knowledge_curator' | 'knowledge_explorator'

export const USER_ROLES: UserRole[] = ['administrator', 'knowledge_curator', 'knowledge_explorator']

export type UserStatus = 'active' | 'suspended'

export interface AdminUser {
  id: string
  email: string
  full_name: string | null
  avatar_url: string | null
  roles: string[]
  capabilities: string[]
  status: string
  /** Research-consent flag: whether AdvanDEB staff may view this user's chats. */
  chat_history_visible_to_admin: boolean
  created_at: string
  updated_at: string
}

export interface UserListResponse {
  items: AdminUser[]
  total: number
  skip: number
  limit: number
}

export interface UserListParams {
  skip?: number
  limit?: number
  q?: string
  role?: string
  status?: string
}

export interface CreateUserPayload {
  email: string
  full_name?: string
  password: string
  roles: string[]
}
