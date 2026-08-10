import { useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

import { getMeRequest, loginRequest, logoutRequest, registerRequest } from '@/api/client'
import type { User } from '@/types'

export interface AuthContextValue {
  /** 로그인한 사용자. 로그인 전에는 null 입니다. */
  user: User | null
  isInitializing: boolean
  login: (email: string, password: string) => Promise<void>
  signup: (name: string, email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function toUser(value: { id: string; email: string; display_name: string }): User {
  return {
    id: value.id,
    name: value.display_name,
    email: value.email,
    color: '#0F73D8',
  }
}

/**
 * 인증 상태 Provider.
 *
 * 화면 컴포넌트의 계약은 유지하고, 이 경계에서만 세션 기반 인증 API를 연결합니다.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isInitializing, setIsInitializing] = useState(true)
  const queryClient = useQueryClient()

  useEffect(() => {
    let active = true
    void getMeRequest()
      .then((value) => {
        if (active) setUser(toUser(value))
      })
      .catch(() => {
        if (active) setUser(null)
      })
      .finally(() => {
        if (active) setIsInitializing(false)
      })
    return () => {
      active = false
    }
  }, [])

  const login: AuthContextValue['login'] = async (email, password) => {
    const value = await loginRequest(email, password)
    queryClient.clear()
    setUser(toUser(value))
  }

  const signup: AuthContextValue['signup'] = async (name, email, password) => {
    await registerRequest(email, password, name)
    queryClient.clear()
    setUser(null)
  }

  const logout: AuthContextValue['logout'] = async () => {
    await logoutRequest()
    queryClient.clear()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, isInitializing, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 는 AuthProvider 내부에서만 사용할 수 있습니다.')
  return ctx
}
