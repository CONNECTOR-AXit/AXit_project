import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

import { currentUser as demoUser } from '@/data/user'
import type { User } from '@/types'

const STORAGE_KEY = 'axit:user'

export interface AuthContextValue {
  /** 로그인한 사용자. 로그인 전에는 null 입니다. */
  user: User | null
  login: (email: string, password: string) => void
  signup: (name: string, email: string, password: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

function readStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

/**
 * 인증 상태 Provider.
 *
 * 지금은 실제 백엔드가 없어 localStorage 에 유저 정보를 저장하는 것으로 로그인 상태를
 * 흉내냅니다. 백엔드 연동 시 login/signup/logout 내부만 실제 API 호출로 교체하면
 * 이 Provider 를 쓰는 화면 쪽 코드는 그대로 둬도 됩니다.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => readStoredUser())

  useEffect(() => {
    if (user) localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
    else localStorage.removeItem(STORAGE_KEY)
  }, [user])

  const login: AuthContextValue['login'] = (email) => {
    // TODO(백엔드 연동): api.post('/auth/login', { email, password }) 응답으로 대체
    // 데모 빌드: 같은 이메일로 가입한 기록이 있으면 그때 입력한 이름을 이어서 씁니다.
    const stored = readStoredUser()
    const name = stored?.email === email ? stored.name : demoUser.name
    setUser({ ...demoUser, name, email })
  }

  const signup: AuthContextValue['signup'] = (name, email) => {
    // TODO(백엔드 연동): api.post('/auth/signup', { name, email, password }) 응답으로 대체
    setUser({ ...demoUser, name, email })
  }

  const logout = () => {
    // TODO(백엔드 연동): api.post('/auth/logout') 호출 및 토큰 폐기 추가
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 는 AuthProvider 내부에서만 사용할 수 있습니다.')
  return ctx
}
