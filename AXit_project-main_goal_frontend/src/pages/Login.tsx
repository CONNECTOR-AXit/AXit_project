import { motion } from 'framer-motion'
import { CheckCircle2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { Logo } from '@/components/common/Logo'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/hooks/useAuth'
import { ApiError } from '@/api/client'

interface FormValues {
  email: string
  password: string
}

type FormErrors = Partial<Record<keyof FormValues, string>>

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function validate(values: FormValues): FormErrors {
  const errors: FormErrors = {}

  if (!values.email.trim()) errors.email = '이메일을 입력해주세요.'
  else if (!EMAIL_PATTERN.test(values.email)) errors.email = '올바른 이메일 형식이 아니에요.'

  if (!values.password) errors.password = '비밀번호를 입력해주세요.'

  return errors
}

/** 로그인 페이지. 화면 구조는 유지하고 인증 Provider를 통해 세션 API를 호출합니다. */
export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()
  const justSignedUp = Boolean((location.state as { justSignedUp?: boolean } | null)?.justSignedUp)

  const [values, setValues] = useState<FormValues>({ email: '', password: '' })
  const [errors, setErrors] = useState<FormErrors>({})
  const [submitted, setSubmitted] = useState(false)
  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const update = (field: keyof FormValues) => (event: React.ChangeEvent<HTMLInputElement>) => {
    setValues((prev) => ({ ...prev, [field]: event.target.value }))
    setErrors((prev) => ({ ...prev, [field]: undefined }))
    setFormError('')
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const nextErrors = validate(values)
    setErrors(nextErrors)
    setSubmitted(true)
    setFormError('')
    if (Object.keys(nextErrors).length === 0) {
      setSubmitting(true)
      try {
        await login(values.email.trim().toLowerCase(), values.password)
        navigate('/')
      } catch (error) {
        setFormError(
          error instanceof ApiError && error.status === 401
            ? '이메일 또는 비밀번호를 확인해주세요.'
            : '로그인 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.',
        )
      } finally {
        setSubmitting(false)
      }
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-canvas px-6 py-12">
      <Link to="/landing">
        <Logo />
      </Link>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-[380px]"
      >
        {justSignedUp && (
          <div className="mb-4 flex items-center gap-2 rounded-lg bg-success-soft px-3.5 py-2.5 text-[13px] font-semibold text-success">
            <CheckCircle2 className="size-4 shrink-0" />
            가입이 완료되었습니다. 로그인해주세요.
          </div>
        )}

        <Card className="p-6">
          <div className="text-center">
            <h1 className="text-[20px] font-extrabold tracking-tight text-ink">로그인</h1>
            <p className="mt-1.5 text-[13px] leading-5 text-ink-muted">
              AXit 계정으로 로그인하세요.
            </p>
          </div>

          <form onSubmit={submit} noValidate className="mt-6 space-y-4">
            {formError && (
              <p
                role="alert"
                className="rounded-lg bg-danger-soft px-3.5 py-2.5 text-[12.5px] font-semibold text-danger"
              >
                {formError}
              </p>
            )}
            <div className="space-y-2">
              <Label htmlFor="login-email">이메일</Label>
              <Input
                id="login-email"
                type="email"
                value={values.email}
                onChange={update('email')}
                placeholder="you@company.com"
                autoComplete="email"
                aria-invalid={submitted && !!errors.email}
              />
              {submitted && errors.email && (
                <p className="text-[12px] font-medium text-danger">{errors.email}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="login-password">비밀번호</Label>
              <Input
                id="login-password"
                type="password"
                value={values.password}
                onChange={update('password')}
                placeholder="비밀번호를 입력해주세요"
                autoComplete="current-password"
                aria-invalid={submitted && !!errors.password}
              />
              {submitted && errors.password && (
                <p className="text-[12px] font-medium text-danger">{errors.password}</p>
              )}
            </div>

            <Button type="submit" variant="gradient" className="w-full" disabled={submitting}>
              {submitting ? '로그인 중...' : '로그인'}
            </Button>
          </form>
        </Card>

        <p className="mt-5 text-center text-[13px] text-ink-muted">
          아직 계정이 없으신가요?{' '}
          <Link to="/signup" className="font-semibold text-primary hover:underline">
            회원가입
          </Link>
        </p>
      </motion.div>
    </div>
  )
}
