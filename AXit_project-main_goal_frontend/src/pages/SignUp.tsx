import { motion } from 'framer-motion'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Logo } from '@/components/common/Logo'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/hooks/useAuth'
import { ApiError } from '@/api/client'

interface FormValues {
  name: string
  email: string
  password: string
  passwordConfirm: string
}

type FormErrors = Partial<Record<keyof FormValues, string>>

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function validate(values: FormValues): FormErrors {
  const errors: FormErrors = {}

  if (!values.name.trim()) errors.name = '이름을 입력해주세요.'

  if (!values.email.trim()) errors.email = '이메일을 입력해주세요.'
  else if (!EMAIL_PATTERN.test(values.email)) errors.email = '올바른 이메일 형식이 아니에요.'

  if (!values.password) errors.password = '비밀번호를 입력해주세요.'
  else if (values.password.length < 8) errors.password = '8자 이상 입력해주세요.'

  if (values.passwordConfirm !== values.password)
    errors.passwordConfirm = '비밀번호가 일치하지 않아요.'

  return errors
}

/** 회원가입 페이지. 화면 구조는 유지하고 인증 Provider를 통해 계정 API를 호출합니다. */
export default function SignUp() {
  const navigate = useNavigate()
  const { signup } = useAuth()
  const [values, setValues] = useState<FormValues>({
    name: '',
    email: '',
    password: '',
    passwordConfirm: '',
  })
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
        await signup(values.name.trim(), values.email.trim().toLowerCase(), values.password)
        navigate('/login', { state: { justSignedUp: true } })
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          setErrors((prev) => ({ ...prev, email: '이미 가입된 이메일입니다.' }))
        } else {
          setFormError('회원가입 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.')
        }
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
        <Card className="p-6">
          <div className="text-center">
            <h1 className="text-[20px] font-extrabold tracking-tight text-ink">회원가입</h1>
            <p className="mt-1.5 text-[13px] leading-5 text-ink-muted">
              AXit에서 문서 통합을 무료로 시작해보세요.
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
              <Label htmlFor="signup-name">이름</Label>
              <Input
                id="signup-name"
                value={values.name}
                onChange={update('name')}
                placeholder="홍길동"
                autoComplete="name"
                aria-invalid={submitted && !!errors.name}
              />
              {submitted && errors.name && (
                <p className="text-[12px] font-medium text-danger">{errors.name}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="signup-email">이메일</Label>
              <Input
                id="signup-email"
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
              <Label htmlFor="signup-password">비밀번호</Label>
              <Input
                id="signup-password"
                type="password"
                value={values.password}
                onChange={update('password')}
                placeholder="8자 이상"
                autoComplete="new-password"
                aria-invalid={submitted && !!errors.password}
              />
              {submitted && errors.password && (
                <p className="text-[12px] font-medium text-danger">{errors.password}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="signup-password-confirm">비밀번호 확인</Label>
              <Input
                id="signup-password-confirm"
                type="password"
                value={values.passwordConfirm}
                onChange={update('passwordConfirm')}
                placeholder="비밀번호를 다시 입력해주세요"
                autoComplete="new-password"
                aria-invalid={submitted && !!errors.passwordConfirm}
              />
              {submitted && errors.passwordConfirm && (
                <p className="text-[12px] font-medium text-danger">{errors.passwordConfirm}</p>
              )}
            </div>

            <Button type="submit" variant="gradient" className="w-full" disabled={submitting}>
              {submitting ? '가입 처리 중...' : '회원가입'}
            </Button>
          </form>
        </Card>

        <p className="mt-5 text-center text-[13px] text-ink-muted">
          이미 계정이 있으신가요?{' '}
          <Link to="/login" className="font-semibold text-primary hover:underline">
            로그인
          </Link>
        </p>
      </motion.div>
    </div>
  )
}
